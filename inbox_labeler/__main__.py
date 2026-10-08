"""Command line: ``python -m inbox_labeler {run,labels,token,check}``.

``run`` classifies a bounded recent-INBOX window with the rule-first pipeline.
It is read-only by default; ``--apply`` only adds an existing label and never
archives, deletes, marks read, removes INBOX, or creates labels.
"""

import argparse
import os
from collections import Counter
from email.utils import parseaddr
from time import perf_counter

from .auth import authorize, check_connection, get_gmail_service
from .gemini import GeminiConfigurationError, GeminiResponseError
from .gmail import (
    add_gmail_label_with_retries,
    ensure_project_labels,
    get_header,
    get_message_metadata,
    list_labels_by_name,
)
from .pipeline import classify_with_fallback, gemini_enabled
from .report import (
    append_github_step_summary,
    build_markdown_summary,
    final_label_rows,
    format_duration,
    percentage,
)
from .rules import RULE_PRIORITY, load_rules

DEFAULT_DAYS = 2
DEFAULT_MESSAGE_LIMIT = 100
MAX_ERROR_LENGTH = 200


def short_error(error):
    """One-line, bounded error text. Failure lines never include sender/subject."""
    return " ".join(str(error).split())[:MAX_ERROR_LENGTH]


def print_summary(
    scanned,
    labeled,
    final_labels,
    skipped_none,
    already_labeled,
    failures,
    apply,
    duration,
):
    mode = "apply" if apply else "dry run"
    metrics = [
        ("Messages scanned", scanned),
        ("Labeled from rules", labeled["rules"]),
        ("Labeled from Gemini", labeled["gemini"]),
        ("Skipped as None", skipped_none),
        ("Already correctly labeled", already_labeled),
        ("API/Gemini failures", len(failures)),
    ]
    print(f"\nDaily processing summary ({mode}):")
    print(f"Messages scanned: {scanned}")
    print(f"Labeled from rules: {labeled['rules']}")
    print(f"Labeled from Gemini: {labeled['gemini']}")
    print(f"Skipped as None: {skipped_none}")
    print(f"Already correctly labeled: {already_labeled}")
    print(f"API/Gemini failures: {len(failures)}")
    print("Outcome breakdown (of messages scanned):")
    for name, count in metrics[1:]:
        print(f"- {name}: {count} ({percentage(count, scanned)})")
    print("Final label counts (of successful classifications):")
    classified = sum(final_labels.values())
    for label, count in final_label_rows(final_labels, RULE_PRIORITY):
        print(f"- {label}: {count} ({percentage(count, classified)})")
    print(f"Execution duration: {format_duration(duration)}")
    for failure in failures:
        print(f"- {failure}")
    append_github_step_summary(
        build_markdown_summary(
            f"Daily processing summary ({mode})",
            metrics,
            final_labels,
            RULE_PRIORITY,
            duration,
        )
    )


def main():
    parser = argparse.ArgumentParser(prog="python -m inbox_labeler")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="Classify recent INBOX messages.")
    run.add_argument(
        "--apply",
        action="store_true",
        help="Add only missing existing project labels after classification.",
    )
    run.add_argument("--days", type=int, default=DEFAULT_DAYS)
    run.add_argument("--max-messages", type=int, default=DEFAULT_MESSAGE_LIMIT)
    run.add_argument(
        "--verbose",
        action="store_true",
        help="Print each classification and action (shows senders and subjects).",
    )
    commands.add_parser("labels", help="Create the labels defined in rules.yaml.")
    commands.add_parser("check", help="Test the Gmail credentials.")
    token = commands.add_parser("token", help="One-time local OAuth setup.")
    token.add_argument("client_secret", nargs="?", default="client_secret.json")
    args = parser.parse_args()

    if args.command == "token":
        return authorize(args.client_secret)
    if args.command == "check":
        return check_connection()
    if args.command == "labels":
        existing, created = ensure_project_labels(get_gmail_service(), RULE_PRIORITY)
        print("Labels already present:", *existing, sep="\n- ")
        print("Labels created:", *created, sep="\n- ")
        return

    if args.days < 1:
        parser.error("--days must be at least 1")
    if args.max_messages < 1:
        parser.error("--max-messages must be at least 1")
    if args.verbose and os.environ.get("GITHUB_ACTIONS") == "true":
        parser.error(
            "--verbose prints senders and subjects and is disabled in GitHub "
            "Actions: run logs of public repositories are visible to everyone."
        )

    started_at = perf_counter()
    rules = load_rules()
    service = get_gmail_service()
    labels_by_name = list_labels_by_name(service)
    print(
        "Gemini fallback:",
        "enabled" if gemini_enabled() else "disabled (rules only)",
    )
    failures = []
    missing_labels = Counter()
    labeled = Counter()
    final_labels = Counter()
    skipped_none = 0
    already_labeled = 0
    scanned = 0

    try:
        response = service.users().messages().list(
            userId="me",
            labelIds=["INBOX"],
            q=f"newer_than:{args.days}d",
            maxResults=args.max_messages,
        ).execute()
        messages = response.get("messages", [])
    except Exception as error:
        print_summary(
            0, labeled, final_labels, 0, 0,
            [f"Gmail list failed: {error}"], args.apply, perf_counter() - started_at,
        )
        return

    try:
        full_messages = get_message_metadata(service, messages)
    except Exception as error:
        print_summary(
            0,
            labeled,
            final_labels,
            0,
            0,
            [f"Gmail metadata fetch failed: {error}"],
            args.apply,
            perf_counter() - started_at,
        )
        return

    for full_message in full_messages:
        scanned += 1
        headers = full_message.get("payload", {}).get("headers", [])
        sender = parseaddr(get_header(headers, "From"))[1]
        subject = get_header(headers, "Subject")

        try:
            result = classify_with_fallback(sender, subject, rules)
        except (GeminiConfigurationError, GeminiResponseError) as error:
            failures.append(
                f"Gemini (message {full_message['id']}): {short_error(error)}"
            )
            continue
        except Exception as error:
            failures.append(
                f"Pipeline (message {full_message['id']}): {short_error(error)}"
            )
            continue

        final_labels[result.label] += 1

        if args.verbose:
            print(f"Sender: {sender}")
            print(f"Subject: {subject}")
            print(f"Final label: {result.label or 'None'}")
            print(f"Source: {result.source}")
            if result.gemini_raw_confidence is not None:
                print(f"Gemini raw confidence: {result.gemini_raw_confidence:.2f}")

        if result.label is None:
            skipped_none += 1
            if args.verbose:
                print("Action: skipped (final label is None)\n")
            continue

        gmail_label = labels_by_name.get(result.label)
        if gmail_label is None:
            missing_labels[result.label] += 1
            if args.verbose:
                print("Action: skipped (required Gmail label is missing)\n")
            continue

        if gmail_label["id"] in full_message.get("labelIds", []):
            already_labeled += 1
            if args.verbose:
                print("Action: skipped (correct label already present)\n")
            continue

        if not args.apply:
            labeled[result.source] += 1
            if args.verbose:
                print("Action: would add label (dry run)\n")
            continue

        try:
            add_gmail_label_with_retries(
                service, full_message["id"], gmail_label["id"]
            )
        except Exception as error:
            failures.append(
                f"Gmail label add (message {full_message['id']}): {short_error(error)}"
            )
            if args.verbose:
                print("Action: failed to add label\n")
            continue

        labeled[result.source] += 1
        if args.verbose:
            print("Action: label added\n")

    for label, count in missing_labels.items():
        failures.append(
            f"Missing Gmail label {label!r} ({count} messages). "
            "Create it once with: python -m inbox_labeler labels"
        )

    print_summary(
        scanned, labeled, final_labels, skipped_none, already_labeled, failures,
        args.apply, perf_counter() - started_at,
    )


if __name__ == "__main__":
    main()
