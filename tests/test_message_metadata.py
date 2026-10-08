"""Focused tests for resilient, ordered Gmail metadata reads."""

from types import SimpleNamespace

from inbox_labeler import gmail


class FakeHttpError(Exception):
    def __init__(self, status):
        self.resp = SimpleNamespace(status=status)
        super().__init__(f"HTTP {status}")


class FakeRequest:
    def __init__(self, service, message_id):
        self.service = service
        self.message_id = message_id

    def execute(self):
        self.service.direct_attempts.append(self.message_id)
        outcome = self.service.direct_outcomes[self.message_id].pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class FakeMessages:
    def __init__(self, service):
        self.service = service

    def get(self, *, id, **_kwargs):
        return FakeRequest(self.service, id)


class FakeUsers:
    def __init__(self, service):
        self.service = service

    def messages(self):
        return FakeMessages(self.service)


class FakeService:
    _baseUrl = "https://gmail.example/"
    _rootDesc = {"batchPath": "batch"}

    def __init__(self, batch_outcomes, direct_outcomes):
        self.batch_outcomes = batch_outcomes
        self.direct_outcomes = direct_outcomes
        self.direct_attempts = []

    def users(self):
        return FakeUsers(self)


class FakeBatchHttpRequest:
    def __init__(self, *, callback, **_kwargs):
        self.callback = callback
        self.requests = []

    def add(self, request, request_id):
        self.requests.append((request, request_id))

    def execute(self):
        for _request, message_id in self.requests:
            outcome = self.requests[0][0].service.batch_outcomes[message_id].pop(0)
            if isinstance(outcome, Exception):
                self.callback(message_id, None, outcome)
            else:
                self.callback(message_id, outcome, None)


def metadata(message_id):
    return {"id": message_id, "payload": {"headers": []}}


def read(service, messages):
    original_batch = gmail.BatchHttpRequest
    original_sleep = gmail.time.sleep
    try:
        gmail.BatchHttpRequest = FakeBatchHttpRequest
        gmail.time.sleep = lambda _seconds: None
        return gmail.get_message_metadata(
            service, messages, allow_partial=True
        )
    finally:
        gmail.BatchHttpRequest = original_batch
        gmail.time.sleep = original_sleep


# A transient 503 is retried and succeeds.
service = FakeService({"one": [FakeHttpError(503)]}, {"one": [metadata("one")]})
messages, failures = read(service, [{"id": "one"}])
assert [message["id"] for message in messages] == ["one"]
assert failures == []
assert service.direct_attempts == ["one"]

# A transient 429 follows the same bounded retry path.
service = FakeService({"two": [FakeHttpError(429)]}, {"two": [metadata("two")]})
messages, failures = read(service, [{"id": "two"}])
assert [message["id"] for message in messages] == ["two"]
assert failures == []
assert service.direct_attempts == ["two"]

# A 403 per-minute rate limit is retried; a plain 403 is not.
class RateLimitError(FakeHttpError):
    def __init__(self, reason):
        super().__init__(403)
        self.content = ('{"error": {"errors": [{"reason": "%s"}]}}' % reason).encode()


service = FakeService(
    {"rate": [RateLimitError("rateLimitExceeded")]}, {"rate": [metadata("rate")]}
)
messages, failures = read(service, [{"id": "rate"}])
assert [message["id"] for message in messages] == ["rate"]
assert failures == []
assert service.direct_attempts == ["rate"]

service = FakeService({"denied": [FakeHttpError(403)]}, {"denied": []})
messages, failures = read(service, [{"id": "denied"}])
assert messages == [] and failures[0][0] == "denied"
assert service.direct_attempts == []

# Permanent 400 and 404 responses are retained as failures with no retry.
for status in (400, 404):
    service = FakeService({"three": [FakeHttpError(status)]}, {"three": []})
    messages, failures = read(service, [{"id": "three"}])
    assert messages == []
    assert failures[0][0] == "three"
    assert gmail.gmail_http_status(failures[0][1]) == status
    assert service.direct_attempts == []

# Two retry attempts after the batched request exhaust a persistent 503.
service = FakeService(
    {"four": [FakeHttpError(503)]},
    {"four": [FakeHttpError(503), FakeHttpError(503)]},
)
messages, failures = read(service, [{"id": "four"}])
assert messages == []
assert failures[0][0] == "four"
assert service.direct_attempts == ["four", "four"]

# A failed read neither aborts the batch nor changes successful-message order.
service = FakeService(
    {
        "first": [metadata("first")],
        "failed": [FakeHttpError(503)],
        "third": [metadata("third")],
    },
    {"first": [], "failed": [FakeHttpError(503), FakeHttpError(503)], "third": []},
)
messages, failures = read(
    service, [{"id": "first"}, {"id": "failed"}, {"id": "third"}]
)
assert [message["id"] for message in messages] == ["first", "third"]
assert [message_id for message_id, _error in failures] == ["failed"]

print("Resilient metadata fetch tests passed")
