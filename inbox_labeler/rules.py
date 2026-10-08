"""Rule-based email classification driven entirely by ``rules.yaml``.

The top-level keys of the rules file are the Gmail label names. Their order is
the priority order (first matching label wins), and each label may carry a
``description`` that is also used to instruct the optional Gemini fallback.

Set ``RULES_PATH`` to load a rules file from somewhere else. It must be set
before this module is imported.
"""

import os
from email.utils import parseaddr
from pathlib import Path
from unicodedata import normalize

import yaml

DEFAULT_RULES_PATH = Path(__file__).resolve().parent.parent / "rules.yaml"
RULES_PATH_ENVIRONMENT_VARIABLE = "RULES_PATH"
LABEL_KEYS = {"description", "rules"}
GROUP_KEYS = {"senders", "keywords"}


class RulesError(ValueError):
    """Raised when the rules file does not follow the expected structure."""


def rules_path(environ=None):
    environ = os.environ if environ is None else environ
    return Path(environ.get(RULES_PATH_ENVIRONMENT_VARIABLE) or DEFAULT_RULES_PATH)


def validate_rules(rules):
    """Check the structure of a loaded rules mapping and return it unchanged."""
    if not isinstance(rules, dict) or not rules:
        raise RulesError(
            "The rules file must be a non-empty mapping of label name -> settings."
        )
    for label, settings in rules.items():
        if not isinstance(label, str) or not label.strip():
            raise RulesError(f"Label names must be non-empty text, got {label!r}.")
        if label.strip().lower() == "none":
            raise RulesError("'None' is reserved and cannot be used as a label name.")
        if settings is None:
            continue
        if not isinstance(settings, dict):
            raise RulesError(f"Label {label!r} must contain 'description' and/or 'rules'.")
        unknown = set(settings) - LABEL_KEYS
        if unknown:
            raise RulesError(f"Label {label!r} has unknown keys: {sorted(unknown)}.")
        if not isinstance(settings.get("description", ""), str):
            raise RulesError(f"Label {label!r}: 'description' must be text.")
        groups = settings.get("rules") or []
        if not isinstance(groups, list):
            raise RulesError(f"Label {label!r}: 'rules' must be a list.")
        for number, group in enumerate(groups, start=1):
            if not isinstance(group, dict):
                raise RulesError(f"Label {label!r}, rule {number}: must be a mapping.")
            unknown = set(group) - GROUP_KEYS
            if unknown:
                raise RulesError(
                    f"Label {label!r}, rule {number}: unknown keys {sorted(unknown)}."
                )
            for key in GROUP_KEYS:
                values = group.get(key) or []
                if not isinstance(values, list) or not all(
                    isinstance(value, str) and value for value in values
                ):
                    raise RulesError(
                        f"Label {label!r}, rule {number}: '{key}' must be a list of "
                        "non-empty text. Quote words YAML reads as booleans "
                        "(for example \"off\", \"no\", \"yes\")."
                    )
    return rules


def load_rules(filepath=None):
    path = Path(filepath) if filepath else rules_path()
    with open(path, "r", encoding="utf-8") as file:
        return validate_rules(yaml.safe_load(file))


def label_priority(rules):
    """Label names in priority order (the order of the rules file)."""
    return list(rules)


def label_descriptions(rules):
    return {
        label: ((settings or {}).get("description") or "").strip()
        for label, settings in rules.items()
    }


_LOADED_RULES = load_rules()
RULE_PRIORITY = label_priority(_LOADED_RULES)
LABEL_DESCRIPTIONS = label_descriptions(_LOADED_RULES)


def classify_email(from_header, subject, rules):
    sender = normalize("NFKC", parseaddr(from_header)[1]).lower()
    subject = normalize("NFKC", subject).lower()
    for label, settings in rules.items():
        for rule_group in (settings or {}).get("rules") or []:
            senders = rule_group.get("senders") or []
            keywords = rule_group.get("keywords") or []

            sender_match = any(sender_rule.lower() in sender for sender_rule in senders)
            keyword_match = any(keyword.lower() in subject for keyword in keywords)

            if senders and keywords:
                matches = sender_match and keyword_match
            elif senders:
                matches = sender_match
            elif keywords:
                matches = keyword_match
            else:
                matches = False

            if matches:
                return label

    return None
