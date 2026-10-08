"""Rule-first classification with an optional Gemini fallback.

This module only classifies sender/subject data. It does not access Gmail or
apply labels.
"""

import os
from dataclasses import dataclass
from typing import Optional

from dotenv import load_dotenv

from .rules import classify_email
from .gemini import GeminiClassification, classify_with_gemini

DISABLED_VALUES = {"0", "false", "no", "off"}


def gemini_enabled(environ=None):
    """Gemini is used only when an API key exists and USE_GEMINI is not false.

    Without a key, or with ``USE_GEMINI=false``, the project runs in rules-only
    mode and no email data is ever sent to Google's Gemini API.
    """
    if environ is None:
        load_dotenv()
        environ = os.environ
    if (environ.get("USE_GEMINI") or "").strip().lower() in DISABLED_VALUES:
        return False
    return bool(environ.get("GEMINI_API_KEY"))


@dataclass(frozen=True)
class PipelineClassification:
    label: Optional[str]
    source: str
    gemini_raw_confidence: Optional[float] = None


class GeminiFallbackUnavailable(RuntimeError):
    """Raised after rules miss while a caller has disabled Gemini fallback."""


def classify_with_fallback(sender, subject, rules, *, gemini_available=True):
    """Classify with local rules first, then Gemini only for rule misses."""
    rule_label = classify_email(sender, subject, rules)
    if rule_label is not None:
        return PipelineClassification(label=rule_label, source="rules")
    if not gemini_enabled():
        return PipelineClassification(label=None, source="none")
    if not gemini_available:
        raise GeminiFallbackUnavailable("Gemini fallback is unavailable for this run")

    gemini_result: GeminiClassification = classify_with_gemini(sender, subject)
    if gemini_result.label is not None:
        return PipelineClassification(
            label=gemini_result.label,
            source="gemini",
            gemini_raw_confidence=gemini_result.raw_confidence,
        )
    return PipelineClassification(
        label=None,
        source="none",
        gemini_raw_confidence=gemini_result.raw_confidence,
    )
