"""Privacy tests: run output and failure lines must not leak sender or subject.

GitHub Actions logs of a public repository are visible to everyone, so the
daily run must only ever log message ids, counts and short error text.
"""

import os
import sys
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO

from inbox_labeler import __main__ as daily

SECRET_SENDER = "private.person@example.com"
SECRET_SUBJECT = "Confidential: private subject line"


def message(message_id):
    return {
        "id": message_id,
        "labelIds": ["INBOX"],
        "internalDate": "1704067200000",
        "payload": {
            "headers": [
                {"name": "From", "value": SECRET_SENDER},
                {"name": "Subject", "value": SECRET_SUBJECT},
            ]
        },
    }


class Execute:
    def __init__(self, value):
        self.value = value

    def execute(self):
        return self.value


class FakeService:
    """Just enough of the Gmail client for ``daily.main`` to list messages."""

    def users(self):
        return self

    def messages(self):
        return self

    def list(self, **_kwargs):
        return Execute({"messages": [{"id": "m1"}, {"id": "m2"}]})


def run_daily(classify, labels, argv=("inbox_labeler", "run")):
    originals = {
        name: getattr(daily, name)
        for name in (
            "load_rules",
            "get_gmail_service",
            "list_labels_by_name",
            "get_message_metadata",
            "classify_with_fallback",
        )
    }
    originals_argv = sys.argv
    daily.load_rules = lambda: {}
    daily.get_gmail_service = lambda: FakeService()
    daily.list_labels_by_name = lambda _service: labels
    daily.get_message_metadata = lambda *_args, **_kwargs: [message("m1"), message("m2")]
    daily.classify_with_fallback = classify
    sys.argv = list(argv)
    output = StringIO()
    try:
        with redirect_stdout(output):
            daily.main()
    finally:
        sys.argv = originals_argv
        for name, value in originals.items():
            setattr(daily, name, value)
    return output.getvalue()


def explode(_sender, _subject, _rules, **_kwargs):
    raise RuntimeError("boom\nwith   extra   whitespace")


# 1. Classification failures name the message id, never sender or subject.
output = run_daily(explode, labels={})
assert "Pipeline (message m1): boom with extra whitespace" in output
assert "Pipeline (message m2)" in output
assert SECRET_SENDER not in output and SECRET_SUBJECT not in output

# 2. A label that does not exist in Gmail is reported once, not once per message.
output = run_daily(
    lambda *_args, **_kwargs: type(
        "Result", (), {"label": "Promotions", "source": "rules", "gemini_raw_confidence": None}
    )(),
    labels={},
)
assert output.count("Missing Gmail label 'Promotions'") == 1
assert "(2 messages)" in output
assert "python -m inbox_labeler labels" in output
assert SECRET_SENDER not in output and SECRET_SUBJECT not in output

# 3. Error text is bounded to one short line.
long_error = "x" * 1000 + "\nsecond line"
assert len(daily.short_error(long_error)) == daily.MAX_ERROR_LENGTH
assert "\n" not in daily.short_error(long_error)

# 4. --verbose (which prints sender and subject) is refused inside GitHub Actions.
previous = os.environ.get("GITHUB_ACTIONS")
os.environ["GITHUB_ACTIONS"] = "true"
sys.argv, original_argv = ["inbox_labeler", "run", "--verbose"], sys.argv
try:
    with redirect_stderr(StringIO()) as errors:
        try:
            daily.main()
        except SystemExit as exit_error:
            assert exit_error.code == 2
        else:
            raise AssertionError("--verbose was allowed in GitHub Actions")
    assert "disabled in GitHub Actions" in errors.getvalue()
finally:
    sys.argv = original_argv
    if previous is None:
        del os.environ["GITHUB_ACTIONS"]
    else:
        os.environ["GITHUB_ACTIONS"] = previous

print("Privacy tests passed")
