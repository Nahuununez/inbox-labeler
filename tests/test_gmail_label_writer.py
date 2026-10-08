"""Focused tests for bounded Gmail label-write retries and flow integration."""

import json
import sys
from copy import deepcopy
from types import SimpleNamespace

from inbox_labeler import __main__ as daily
from inbox_labeler import gmail
from inbox_labeler.rules import RULE_PRIORITY
from inbox_labeler.gmail import (
    add_gmail_label_with_retries,
    gmail_error_reasons,
    is_retriable_gmail_error,
)


class FakeHttpError(Exception):
    def __init__(self, status, reason=None):
        self.resp = SimpleNamespace(status=status)
        errors = [] if reason is None else [{"reason": reason}]
        self.content = json.dumps({"error": {"errors": errors}}).encode()
        super().__init__(f"HTTP {status}: {reason or 'error'}")


class FakeModifyRequest:
    def __init__(self, service, message_id, body):
        self.service = service
        self.message_id = message_id
        self.body = body

    def execute(self):
        self.service.modify_attempts.append((self.message_id, deepcopy(self.body)))
        outcome = self.service.modify_outcomes[self.message_id].pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class FakeListRequest:
    def __init__(self, message_ids):
        self.message_ids = message_ids

    def execute(self):
        return {"messages": [{"id": message_id} for message_id in self.message_ids]}


class FakeMessages:
    def __init__(self, service):
        self.service = service

    def list(self, **_kwargs):
        return FakeListRequest(list(self.service.modify_outcomes))

    def modify(self, *, id, body, **_kwargs):
        return FakeModifyRequest(self.service, id, body)


class FakeUsers:
    def __init__(self, service):
        self.service = service

    def messages(self):
        return FakeMessages(self.service)


class FakeService:
    def __init__(self, modify_outcomes):
        self.modify_outcomes = {
            message_id: list(outcomes)
            for message_id, outcomes in modify_outcomes.items()
        }
        self.modify_attempts = []

    def users(self):
        return FakeUsers(self)


def write(outcomes):
    service = FakeService({"message": outcomes})
    delays = []
    try:
        response = add_gmail_label_with_retries(
            service, "message", "label", sleep=delays.append
        )
        error = None
    except Exception as caught:
        response = None
        error = caught
    return service, delays, response, error


# Success on the initial request performs one write and no sleep.
service, delays, response, error = write([{"id": "message"}])
assert error is None and response == {"id": "message"}
assert service.modify_attempts == [("message", {"addLabelIds": ["label"]})]
assert delays == []

# A structured Gmail rate-limit 403 is retried, preserving the exact write.
service, delays, _response, error = write(
    [FakeHttpError(403, "rateLimitExceeded"), {"id": "message"}]
)
assert error is None
assert len(service.modify_attempts) == 2
assert len(set(json.dumps(body, sort_keys=True) for _, body in service.modify_attempts)) == 1
assert delays == [1]

# Both documented Gmail per-user rate-limit reasons are narrowly retryable.
user_rate_error = FakeHttpError(403, "userRateLimitExceeded")
assert is_retriable_gmail_error(user_rate_error)
assert gmail_error_reasons(user_rate_error) == {"userratelimitexceeded"}

# The initial request plus three retries is the complete bounded budget.
service, delays, _response, error = write(
    [FakeHttpError(403, "rateLimitExceeded") for _ in range(4)]
)
assert isinstance(error, FakeHttpError)
assert len(service.modify_attempts) == 4
assert delays == [1, 2, 4]

# Transient server errors share the same increasing backoff and can recover.
service, delays, _response, error = write(
    [FakeHttpError(500), FakeHttpError(503), {"id": "message"}]
)
assert error is None
assert len(service.modify_attempts) == 3
assert delays == [1, 2]

# HTTP 429 is transient even when no structured reason is present.
service, delays, _response, error = write(
    [FakeHttpError(429), {"id": "message"}]
)
assert error is None
assert len(service.modify_attempts) == 2
assert delays == [1]

# Permanent client errors and generic 403s are attempted only once.
for permanent_error in (
    FakeHttpError(400),
    FakeHttpError(401),
    FakeHttpError(404),
    FakeHttpError(403, "forbidden"),
):
    service, delays, _response, error = write([permanent_error])
    assert error is permanent_error
    assert len(service.modify_attempts) == 1
    assert delays == []


def message(message_id, sender):
    return {
        "id": message_id,
        "labelIds": ["INBOX"],
        "internalDate": "1704067200000",
        "payload": {
            "headers": [
                {"name": "From", "value": sender},
                {"name": "Subject", "value": f"Subject {message_id}"},
            ]
        },
    }


labels = {label: {"id": label} for label in RULE_PRIORITY}

# Daily rule labels also use the shared protected write path without re-running
# classification when the first write is transiently rejected.
daily_service = FakeService(
    {"daily": [FakeHttpError(503), {"id": "daily", "labelIds": ["Education"]}]}
)
daily_classifications = []
daily_delays = []
daily_summary = {}


def daily_fallback(sender, _subject, _rules, **_kwargs):
    daily_classifications.append(sender)
    return SimpleNamespace(
        label="Education", source="rules", gemini_raw_confidence=None
    )


def capture_daily_summary(
    scanned, labeled, final_labels, skipped_none, already_labeled, failures, *_args
):
    daily_summary.update(
        scanned=scanned,
        labeled=labeled,
        final_labels=final_labels,
        skipped_none=skipped_none,
        already_labeled=already_labeled,
        failures=failures,
    )


daily_originals = {
    "argv": sys.argv,
    "load_rules": daily.load_rules,
    "get_gmail_service": daily.get_gmail_service,
    "list_labels_by_name": daily.list_labels_by_name,
    "get_message_metadata": daily.get_message_metadata,
    "classify_with_fallback": daily.classify_with_fallback,
    "print_summary": daily.print_summary,
    "sleep": gmail.time.sleep,
}
try:
    sys.argv = ["inbox_labeler", "run", "--apply", "--max-messages", "1"]
    daily.load_rules = lambda: {}
    daily.get_gmail_service = lambda: daily_service
    daily.list_labels_by_name = lambda _service: labels
    daily.get_message_metadata = lambda *_args, **_kwargs: [
        message("daily", "daily@example.com")
    ]
    daily.classify_with_fallback = daily_fallback
    daily.print_summary = capture_daily_summary
    gmail.time.sleep = daily_delays.append
    daily.main()
finally:
    sys.argv = daily_originals["argv"]
    daily.load_rules = daily_originals["load_rules"]
    daily.get_gmail_service = daily_originals["get_gmail_service"]
    daily.list_labels_by_name = daily_originals["list_labels_by_name"]
    daily.get_message_metadata = daily_originals["get_message_metadata"]
    daily.classify_with_fallback = daily_originals["classify_with_fallback"]
    daily.print_summary = daily_originals["print_summary"]
    gmail.time.sleep = daily_originals["sleep"]

assert daily_classifications == ["daily@example.com"]
assert [message_id for message_id, _body in daily_service.modify_attempts] == [
    "daily",
    "daily",
]
assert daily_delays == [1]
assert daily_summary["scanned"] == 1
assert daily_summary["labeled"]["rules"] == 1
assert daily_summary["failures"] == []

print("Gmail label writer retry tests passed")


# execute_with_retries waits and retries per-minute rate limits, then succeeds.
class FlakyRequest:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)

    def execute(self):
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


waits = []
result = gmail.execute_with_retries(
    FlakyRequest([FakeHttpError(403, "rateLimitExceeded"), {"ok": True}]),
    sleep=waits.append,
)
assert result == {"ok": True} and waits == [gmail.REQUEST_RETRY_DELAYS_SECONDS[0]]

# A permanent error is raised immediately, without waiting.
waits = []
try:
    gmail.execute_with_retries(FlakyRequest([FakeHttpError(404)]), sleep=waits.append)
except FakeHttpError:
    pass
else:
    raise AssertionError("a 404 must not be retried")
assert waits == []
