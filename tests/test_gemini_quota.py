"""Focused tests for Gemini temporary-rate and daily-quota behavior."""

from types import SimpleNamespace

from inbox_labeler import gemini
from inbox_labeler.gemini import (
    GeminiDailyQuotaExhausted,
    GeminiRequestStats,
    classify_with_gemini,
    is_daily_quota_exhausted,
)


class FakeGeminiError(Exception):
    def __init__(self, details):
        self.code = 429
        self.details = details
        super().__init__("RESOURCE_EXHAUSTED")


class FakeRateLimiter:
    def __init__(self):
        self.wait_calls = 0
        self.deferred = []

    def wait_for_turn(self, _stats):
        self.wait_calls += 1

    def defer(self, seconds):
        self.deferred.append(seconds)


class FakeModels:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    def generate_content(self, **_kwargs):
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return SimpleNamespace(text=outcome)


class FakeClient:
    def __init__(self, outcomes):
        self.models = FakeModels(outcomes)


temporary_429 = FakeGeminiError(
    {"error": {"details": [{"retryDelay": "1s", "reason": "RATE_LIMIT"}]}}
)
daily_quota_429 = FakeGeminiError(
    {
        "error": {
            "details": [
                {
                    "quotaMetric": "generativelanguage.googleapis.com/generate_content_free_tier_requests",
                    "quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier",
                    "quotaValue": "500",
                }
            ]
        }
    }
)

assert not is_daily_quota_exhausted(temporary_429)
assert is_daily_quota_exhausted(daily_quota_429)

original_client = gemini.get_gemini_client
try:
    # A temporary 429 preserves the existing retry path and later succeeds.
    temporary_client = FakeClient(
        [temporary_429, '{"label":"Education","confidence":0.99}']
    )
    gemini.get_gemini_client = lambda **_kwargs: temporary_client
    limiter = FakeRateLimiter()
    stats = GeminiRequestStats()
    result = classify_with_gemini(
        "student@example.com",
        "Course update",
        rate_limiter=limiter,
        stats=stats,
    )
    assert result.label == "Education"
    assert temporary_client.models.calls == 2
    assert stats.rate_limit_retries == 1
    assert limiter.deferred == [gemini.DEFAULT_RATE_LIMIT_WAIT_SECONDS]

    # A confirmed daily quota error fails immediately without a retry/defer.
    daily_client = FakeClient([daily_quota_429])
    gemini.get_gemini_client = lambda **_kwargs: daily_client
    limiter = FakeRateLimiter()
    try:
        classify_with_gemini(
            "student@example.com", "Course update", rate_limiter=limiter
        )
    except GeminiDailyQuotaExhausted:
        pass
    else:
        raise AssertionError("daily quota exhaustion was retried instead of surfaced")
    assert daily_client.models.calls == 1
    assert limiter.deferred == []
finally:
    gemini.get_gemini_client = original_client

print("Gemini quota tests passed")
