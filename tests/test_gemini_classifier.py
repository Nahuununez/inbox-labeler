"""Local tests for Gemini response validation and confidence thresholding."""

import json

from inbox_labeler.rules import LABEL_DESCRIPTIONS, RULE_PRIORITY
import os

from inbox_labeler.gemini import (
    DEFAULT_CONFIDENCE_THRESHOLD,
    DEFAULT_MODEL,
    GeminiResponseError,
    _confidence_threshold,
    _model_name,
    _parse_classification,
    _prompt,
)


def response(label, confidence):
    return json.dumps({"label": label, "confidence": confidence})


# A confidence equal to the threshold is accepted.
result = _parse_classification(response("Promotions", 0.95))
assert result.label == "Promotions"
assert result.raw_label == "Promotions"
assert result.raw_confidence == 0.95

# A lower confidence remains available as raw data but is not accepted.
result = _parse_classification(response("Promotions", 0.94))
assert result.label is None
assert result.raw_label == "Promotions"
assert result.raw_confidence == 0.94

# Gemini's explicit None must remain None regardless of confidence.
result = _parse_classification(response(None, 0.99))
assert result.label is None
assert result.raw_label is None

# Validation remains strict before applying the confidence threshold.
try:
    _parse_classification(response("Made-Up-Label", 1.0))
except GeminiResponseError:
    pass
else:
    raise AssertionError("unsupported Gemini label was accepted")

# The prompt is built from rules.yaml: every label and its description appear,
# and nothing hard-coded about a specific mailbox leaks into it.
prompt = _prompt("sender@example.com", "Some subject")
for label in RULE_PRIORITY:
    assert f"- {label}: {LABEL_DESCRIPTIONS[label]}" in prompt
assert "Sender email: sender@example.com" in prompt
assert prompt.endswith("Subject: Some subject")

# GitHub Actions passes unset repository variables as empty strings: they must
# fall back to the defaults instead of breaking the Gemini call.
os.environ["GEMINI_MODEL"] = ""
os.environ["GEMINI_CONFIDENCE_THRESHOLD"] = ""
assert _model_name() == DEFAULT_MODEL
assert _confidence_threshold() == DEFAULT_CONFIDENCE_THRESHOLD
os.environ["GEMINI_MODEL"] = "custom-model"
os.environ["GEMINI_CONFIDENCE_THRESHOLD"] = "0.8"
assert _model_name() == "custom-model"
assert _model_name("explicit-model") == "explicit-model"
assert _confidence_threshold() == 0.8
del os.environ["GEMINI_MODEL"], os.environ["GEMINI_CONFIDENCE_THRESHOLD"]

print("Gemini confidence-threshold tests passed")
