"""Local tests for rule-first Gemini fallback orchestration."""

import os

from inbox_labeler import pipeline
from inbox_labeler.gemini import GeminiClassification
from inbox_labeler.pipeline import GeminiFallbackUnavailable, gemini_enabled

# Gemini only runs with an API key; the tests below assume it is configured.
os.environ["GEMINI_API_KEY"] = "test-key-not-used"
os.environ.pop("USE_GEMINI", None)


def gemini_result(label, confidence, raw_label=None):
    return GeminiClassification(
        label=label,
        confidence=confidence,
        raw_label=label if raw_label is None else raw_label,
        raw_confidence=confidence,
    )


calls = []


def fake_rules_match(sender, subject, rules):
    return "Promotions"


def fail_if_called(sender, subject):
    raise AssertionError("Gemini should not run for a rule match")


pipeline.classify_email = fake_rules_match
pipeline.classify_with_gemini = fail_if_called
result = pipeline.classify_with_fallback("sender@example.com", "offer", {})
assert result.label == "Promotions" and result.source == "rules"


def fake_rules_none(sender, subject, rules):
    return None


def accepted_gemini(sender, subject):
    calls.append((sender, subject))
    return gemini_result("Education", 0.97)


pipeline.classify_email = fake_rules_none
pipeline.classify_with_gemini = accepted_gemini
result = pipeline.classify_with_fallback("student@example.com", "new course", {})
assert calls == [("student@example.com", "new course")]
assert result.label == "Education"
assert result.source == "gemini"
assert result.gemini_raw_confidence == 0.97


def rejected_gemini(sender, subject):
    return gemini_result(None, 0.94, raw_label="Promotions")


pipeline.classify_with_gemini = rejected_gemini
result = pipeline.classify_with_fallback("shop@example.com", "sale", {})
assert result.label is None
assert result.source == "none"
assert result.gemini_raw_confidence == 0.94


def none_gemini(sender, subject):
    return gemini_result(None, 1.0)


pipeline.classify_with_gemini = none_gemini
result = pipeline.classify_with_fallback("security@example.com", "new device", {})
assert result.label is None
assert result.source == "none"
assert result.gemini_raw_confidence == 1.0

# Disabling Gemini for one caller still lets deterministic rules classify.
pipeline.classify_email = fake_rules_match
pipeline.classify_with_gemini = fail_if_called
result = pipeline.classify_with_fallback(
    "sender@example.com", "offer", {}, gemini_available=False
)
assert result.label == "Promotions" and result.source == "rules"

# A rule miss with Gemini disabled makes no Gemini call and is explicitly deferred.
pipeline.classify_email = fake_rules_none
try:
    pipeline.classify_with_fallback(
        "sender@example.com", "offer", {}, gemini_available=False
    )
except GeminiFallbackUnavailable:
    pass
else:
    raise AssertionError("disabled Gemini fallback was not deferred")

# --- Gemini is optional -------------------------------------------------
assert gemini_enabled({"GEMINI_API_KEY": "key"}) is True
assert gemini_enabled({}) is False  # no key: rules-only mode
assert gemini_enabled({"GEMINI_API_KEY": ""}) is False
for off in ("false", "FALSE", "0", "no", "off", " False "):
    assert gemini_enabled({"GEMINI_API_KEY": "key", "USE_GEMINI": off}) is False
assert gemini_enabled({"GEMINI_API_KEY": "key", "USE_GEMINI": "true"}) is True

# Rules-only mode: rules still classify, and a rule miss is a plain None
# (not a failure) without any Gemini call, so no mail data leaves the machine.
os.environ["USE_GEMINI"] = "false"
pipeline.classify_email = fake_rules_match
pipeline.classify_with_gemini = fail_if_called
result = pipeline.classify_with_fallback("sender@example.com", "offer", {})
assert result.label == "Promotions" and result.source == "rules"

pipeline.classify_email = fake_rules_none
result = pipeline.classify_with_fallback("sender@example.com", "offer", {})
assert result.label is None and result.source == "none"
assert result.gemini_raw_confidence is None
del os.environ["USE_GEMINI"]

print("Pipeline tests passed")
