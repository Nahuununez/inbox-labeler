"""Optional, isolated Gemini classifier for messages not matched by local rules.

This module never reads or changes Gmail.  It sends only a sender email address
and subject to Gemini and restricts the response to the existing project
labels (or ``None``).
"""

import json
import os
import re
import time
from dataclasses import dataclass, field
from typing import Optional

from dotenv import load_dotenv
from google import genai
from google.genai import types

from .rules import LABEL_DESCRIPTIONS, RULE_PRIORITY

# Gemini no longer permits new users to generate with 2.5 Flash-Lite.
DEFAULT_MODEL = "gemini-3.1-flash-lite"
DEFAULT_CONFIDENCE_THRESHOLD = 0.95
RATE_LIMIT_STATUS = 429
RETRYABLE_SERVER_STATUSES = {500, 502, 503, 504}
MAX_ATTEMPTS = 2
# A rate-limited request waits ~60s before its retry, so allow just one retry.
MAX_RATE_LIMIT_ATTEMPTS = 2
RETRY_DELAY_SECONDS = 1
FREE_TIER_REQUESTS_PER_MINUTE = 12
MIN_REQUEST_INTERVAL_SECONDS = 60 / FREE_TIER_REQUESTS_PER_MINUTE
DEFAULT_RATE_LIMIT_WAIT_SECONDS = 60
GEMINI_HTTP_TIMEOUT_MILLISECONDS = 20_000


class GeminiConfigurationError(RuntimeError):
    """Raised when the optional Gemini API key has not been configured."""


class GeminiResponseError(RuntimeError):
    """Raised when Gemini cannot return the required structured response."""


class GeminiRateLimitExhausted(GeminiResponseError):
    """Raised when Gemini keeps answering 429 after the allowed retries."""


class GeminiDailyQuotaExhausted(GeminiResponseError):
    """Raised when Gemini reports its daily free-tier quota is exhausted."""


@dataclass(frozen=True)
class GeminiClassification:
    label: Optional[str]
    confidence: float
    raw_label: Optional[str]
    raw_confidence: float


@dataclass
class GeminiRequestStats:
    rate_limit_waits: int = 0
    rate_limit_retries: int = 0
    other_transient_retries: int = 0


@dataclass
class GeminiRateLimiter:
    """Conservatively space Gemini request starts below the free-tier RPM cap."""

    minimum_interval_seconds: float = MIN_REQUEST_INTERVAL_SECONDS
    next_request_at: float = field(default=0.0)

    def wait_for_turn(self, stats):
        delay = self.next_request_at - time.monotonic()
        if delay > 0:
            stats.rate_limit_waits += 1
            time.sleep(delay)
        self.next_request_at = time.monotonic() + self.minimum_interval_seconds

    def defer(self, delay_seconds):
        self.next_request_at = max(
            self.next_request_at, time.monotonic() + delay_seconds
        )


DEFAULT_RATE_LIMITER = GeminiRateLimiter()


def _response_schema():
    return {
        "type": "object",
        "properties": {
            "label": {
                "type": ["string", "null"],
                "enum": [*RULE_PRIORITY, None],
                "description": "One existing project label, or null when uncertain.",
            },
            "confidence": {
                "type": "number",
                "minimum": 0,
                "maximum": 1,
                "description": "Confidence from 0.0 to 1.0.",
            },
        },
        "required": ["label", "confidence"],
    }


def _prompt(sender: str, subject: str):
    labels = ", ".join(RULE_PRIORITY)
    definitions = "\n".join(
        f"- {label}: {LABEL_DESCRIPTIONS.get(label) or 'No description provided.'}"
        for label in RULE_PRIORITY
    )
    return (
        "Classify this email using only the sender email and subject. Return one "
        f"of these exact labels or null: {labels}. Never create, rename, or infer "
        "another label. Prefer null whenever no category fits cleanly or the evidence "
        "is ambiguous.\n\n"
        f"Label definitions:\n{definitions}\n\n"
        "Security, account-access, password, device, login, verification, and service "
        "notifications must return null unless the sender and subject genuinely satisfy "
        "one definition above.\n\n"
        f"Sender email: {sender}\n"
        f"Subject: {subject}"
    )


def _model_name(model=None):
    """Explicit model, else GEMINI_MODEL, else the default (empty values ignored)."""
    return model or os.getenv("GEMINI_MODEL") or DEFAULT_MODEL


def _confidence_threshold(value=None):
    value = value if value is not None else os.getenv("GEMINI_CONFIDENCE_THRESHOLD")
    if value is None or value == "":
        return DEFAULT_CONFIDENCE_THRESHOLD
    try:
        threshold = float(value)
    except (TypeError, ValueError) as error:
        raise GeminiConfigurationError(
            "GEMINI_CONFIDENCE_THRESHOLD must be a number between 0 and 1."
        ) from error
    if not 0 <= threshold <= 1:
        raise GeminiConfigurationError(
            "GEMINI_CONFIDENCE_THRESHOLD must be between 0 and 1."
        )
    return threshold


def _parse_classification(response_text, *, confidence_threshold=None):
    try:
        parsed = json.loads(response_text)
        raw_label = parsed["label"]
        confidence = float(parsed["confidence"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise GeminiResponseError("Gemini returned invalid structured classification") from error

    if raw_label is not None and raw_label not in RULE_PRIORITY:
        raise GeminiResponseError(f"Gemini returned an unsupported label: {raw_label!r}")
    if not 0 <= confidence <= 1:
        raise GeminiResponseError("Gemini confidence must be between 0 and 1")
    threshold = _confidence_threshold(confidence_threshold)
    accepted_label = (
        raw_label
        if raw_label is None or confidence >= threshold
        else None
    )
    return GeminiClassification(
        label=accepted_label,
        confidence=confidence,
        raw_label=raw_label,
        raw_confidence=confidence,
    )


def get_gemini_client(*, api_key=None):
    """Create the official Gemini Developer API client without exposing its key."""
    load_dotenv()
    api_key = api_key or os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise GeminiConfigurationError(
            "GEMINI_API_KEY is not configured. Add it to the environment or .env."
        )
    return genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(
            timeout=GEMINI_HTTP_TIMEOUT_MILLISECONDS,
            # Let this module's explicit 429 and 5xx policy control retries.
            retry_options=types.HttpRetryOptions(attempts=1),
        ),
    )


def _http_status(error):
    """Extract a Gemini SDK HTTP status without relying on an error string."""
    try:
        return int(getattr(error, "code", None))
    except (TypeError, ValueError):
        return None


def _retry_delay_from_error(error):
    """Read Gemini's retry delay when the API provides one."""
    details = getattr(error, "details", {})
    try:
        violations = details["error"]["details"]
    except (KeyError, TypeError):
        return None

    for violation in violations:
        retry_delay = violation.get("retryDelay")
        if isinstance(retry_delay, str):
            match = re.fullmatch(r"(\d+(?:\.\d+)?)s", retry_delay)
            if match:
                return float(match.group(1))
    return None


def is_daily_quota_exhausted(error):
    """Identify Gemini's explicit per-day quota response without matching RPM 429s."""
    if _http_status(error) != RATE_LIMIT_STATUS:
        return False
    details = getattr(error, "details", "")
    try:
        details = json.dumps(details, sort_keys=True, default=str)
    except (TypeError, ValueError):
        details = str(details)
    quota_text = f"{error} {details}".casefold().replace("_", "").replace("-", "")
    return (
        "generaterequestsperdayperprojectpermodel" in quota_text
        or "requestsperday" in quota_text
    )


def classify_with_gemini(
    sender: str,
    subject: str,
    *,
    api_key=None,
    model=None,
    confidence_threshold=None,
    rate_limiter=None,
    stats=None,
):
    """Return a structured Gemini classification for one sender/subject pair.

    ``GEMINI_API_KEY`` is intentionally the only new configuration required;
    it is loaded from the existing project ``.env`` or the process environment.
    The default Flash-Lite model and single-message requests are chosen to stay
    within Gemini's free-tier usage limits.
    """
    model = _model_name(model)
    client = get_gemini_client(api_key=api_key)
    rate_limiter = rate_limiter or DEFAULT_RATE_LIMITER
    stats = stats or GeminiRequestStats()
    for attempt in range(MAX_ATTEMPTS):
        rate_limiter.wait_for_turn(stats)
        try:
            response = client.models.generate_content(
                model=model,
                contents=_prompt(sender, subject),
                config=types.GenerateContentConfig(
                    temperature=0,
                    max_output_tokens=64,
                    response_mime_type="application/json",
                    response_json_schema=_response_schema(),
                    automatic_function_calling=types.AutomaticFunctionCallingConfig(
                        disable=True
                    ),
                ),
            )
            break
        except Exception as error:
            status = _http_status(error)
            if status == RATE_LIMIT_STATUS:
                if is_daily_quota_exhausted(error):
                    raise GeminiDailyQuotaExhausted(
                        f"Gemini daily quota exhausted for model {model!r}: {error}"
                    ) from error
                stats.rate_limit_retries += 1
                if attempt >= MAX_RATE_LIMIT_ATTEMPTS - 1:
                    raise GeminiRateLimitExhausted(
                        f"Gemini API request failed for model {model!r}: {error}"
                    ) from error
                rate_limiter.defer(
                    max(
                        _retry_delay_from_error(error) or 0,
                        DEFAULT_RATE_LIMIT_WAIT_SECONDS,
                    )
                )
                continue
            if status not in RETRYABLE_SERVER_STATUSES or attempt == MAX_ATTEMPTS - 1:
                raise GeminiResponseError(
                    f"Gemini API request failed for model {model!r}: {error}"
                ) from error
            stats.other_transient_retries += 1
            time.sleep(RETRY_DELAY_SECONDS * (2**attempt))

    if not response.text:
        raise GeminiResponseError("Gemini returned no structured response text")
    return _parse_classification(
        response.text, confidence_threshold=confidence_threshold
    )


def check_model(*, model=None, api_key=None):
    """Classify one fictional message; return (model, label, seconds).

    Nothing from the mailbox is sent. Raises the usual Gemini errors, so the
    caller can show why a model does not work (overloaded, wrong name, quota).
    """
    model = _model_name(model)
    started_at = time.perf_counter()
    result = classify_with_gemini(
        "newsletter@example.com",
        "Your weekly digest",
        model=model,
        api_key=api_key,
    )
    return model, result.label, time.perf_counter() - started_at


def list_generate_models(*, api_key=None):
    """Names of the models that accept ``generateContent``, sorted."""
    client = get_gemini_client(api_key=api_key)
    return sorted(
        model.name.removeprefix("models/")
        for model in client.models.list()
        if "generateContent" in (model.supported_actions or [])
    )
