"""Local tests for rule loading, validation, priority and classification.

All addresses and subjects below are fictional or generic examples; no real
mailbox data is used. Run with ``python -m tests``.
"""

import tempfile
from pathlib import Path
from unicodedata import normalize

from inbox_labeler.rules import (
    LABEL_DESCRIPTIONS,
    RULE_PRIORITY,
    RulesError,
    classify_email,
    label_priority,
    load_rules,
    validate_rules,
)

rules = load_rules()

# --- The shipped starter rules are well formed and fully described ----------
assert RULE_PRIORITY == label_priority(rules)
assert RULE_PRIORITY[:2] == ["Jobs-Applications", "Jobs-Offers"]
assert all(LABEL_DESCRIPTIONS[label] for label in RULE_PRIORITY), (
    "every label needs a description: Gemini uses it to classify rule misses"
)

# --- Classification of generic example messages ---------------------------
tests = [
    # Jobs-Applications
    ("LinkedIn <jobs-noreply@linkedin.com>", "Your application was sent to Acme Corp", "Jobs-Applications"),
    ("Careers <no-reply@careers.example.com>", "Thank you for applying to Acme", "Jobs-Applications"),
    ("Indeed <noreply@indeed.com>", "Application received for Data Analyst", "Jobs-Applications"),
    ("Empleos <no-reply@empleos.example.com>", "Recibimos tu postulación", "Jobs-Applications"),
    # Jobs-Offers
    ("LinkedIn <jobs-noreply@linkedin.com>", "New job alert: Data Analyst (Remote)", "Jobs-Offers"),
    ("Indeed <noreply@indeed.com>", "10 new jobs for you", "Jobs-Offers"),
    ("Glassdoor <noreply@glassdoor.com>", "Acme is hiring a Junior Analyst", "Jobs-Offers"),
    ("NOREPLY@LINKEDIN.COM", "JOB ALERT: Python Developer", "Jobs-Offers"),
    # Banking-Transactional
    ("PayPal <service@paypal.com>", "You sent a payment of $20.00", "Banking-Transactional"),
    ("Example Bank <alerts@examplebank.com>", "Your statement is ready", "Banking-Transactional"),
    ("Wise <noreply@wise.com>", "Your transfer is on its way", "Banking-Transactional"),
    ("Banco Ejemplo <avisos@bancoejemplo.com>", "Resumen de tu tarjeta", "Banking-Transactional"),
    # Banking-Promos
    ("Revolut <hello@revolut.com>", "Get 5% cashback on travel", "Banking-Promos"),
    ("Banco Ejemplo <promos@bancoejemplo.com>", "Beneficios y cuotas sin interés", "Banking-Promos"),
    # Promotions
    ("Shoe Store <newsletter@shoes.example.com>", "Summer sale: 40% off everything", "Promotions"),
    ("Deals <deals@store.example.com>", "Free shipping this weekend", "Promotions"),
    ("Tienda <marketing@tienda.example.com>", "Descuento exclusivo para vos", "Promotions"),
    # Social-Networking
    ("LinkedIn <invitations@linkedin.com>", "Alex wants to connect with you", "Social-Networking"),
    ("Facebook <notification@facebookmail.com>", "Sam commented on your post", "Social-Networking"),
    ("Reddit <noreply@reddit.com>", "You have a new follower", "Social-Networking"),
    # Government-Local
    ("City Hall <info@city.example.gov>", "Notice about your parking permit", "Government-Local"),
    ("Tax Office <aviso@oficina.example.gob.ar>", "Constancia disponible", "Government-Local"),
    # Subscriptions-Receipts
    ("Netflix <info@netflix.com>", "Your subscription renewal receipt", "Subscriptions-Receipts"),
    ("Acme Store <orders@acme.example.com>", "Order confirmation #1234", "Subscriptions-Receipts"),
    ("Billing <billing@saas.example.com>", "Your invoice for October", "Subscriptions-Receipts"),
    ("Tienda <no-reply@tienda.example.com>", "Tu factura está disponible", "Subscriptions-Receipts"),
    # Education
    ("Coursera <no-reply@coursera.org>", "New lesson available", "Education"),
    ("University <info@uni.example.edu>", "Class schedule update", "Education"),
    ("Duolingo <hello@duolingo.com>", "Time for your daily practice", "Education"),
    # Priority between labels: a receipt from a learning platform is a receipt.
    ("Udemy <no-reply@udemy.com>", "Your receipt for the Python course", "Subscriptions-Receipts"),
    # Messages that should stay unlabeled
    ("Example Bank <security@examplebank.com>", "Your verification code is 123456", None),
    ("LinkedIn <updates@linkedin.com>", "Your weekly profile update", None),
    ("Alice <alice@example.com>", "Sale of the old car", None),
    ("Alice <alice@example.com>", "Dinner on Friday?", None),
]

for from_header, subject, expected in tests:
    result = classify_email(from_header, subject, rules)
    assert result == expected, (
        f"Expected {expected!r} for {subject!r} from {from_header!r}, got {result!r}"
    )

# Accents are normalized, so decomposed (NFD) text still matches.
assert (
    classify_email(
        "Empleos <no-reply@empleos.example.com>",
        normalize("NFD", "Recibimos tu postulación"),
        rules,
    )
    == "Jobs-Applications"
)

# --- Rule semantics, on tiny custom rules ---------------------------------
custom = {
    "Second-In-File-Order-Is-Lower-Priority": {"rules": [{"keywords": ["match"]}]},
    "Sender-Only": {"rules": [{"senders": ["only.example"]}]},
    "Sender-And-Keyword": {"rules": [{"senders": ["both.example"], "keywords": ["hello"]}]},
}
assert label_priority(custom) == list(custom)
assert classify_email("a@x.example", "a match", custom) == "Second-In-File-Order-Is-Lower-Priority"
assert classify_email("a@only.example", "anything", custom) == "Sender-Only"
assert classify_email("a@both.example", "hello there", custom) == "Sender-And-Keyword"
assert classify_email("a@both.example", "bye", custom) is None  # needs sender AND keyword

# The first label in the file wins when several could match.
first_wins = {
    "First": {"rules": [{"keywords": ["x"]}]},
    "Second": {"rules": [{"keywords": ["x"]}]},
}
assert classify_email("a@b.example", "x", first_wins) == "First"
assert classify_email("a@b.example", "x", dict(reversed(list(first_wins.items())))) == "Second"

# A label without rules (description only) never matches but is still valid.
assert classify_email("a@b.example", "x", {"Empty": None, "Docs": {"description": "d"}}) is None

# --- Validation catches the usual YAML mistakes ---------------------------
def assert_invalid(candidate, message_part):
    try:
        validate_rules(candidate)
    except RulesError as error:
        assert message_part in str(error), (message_part, str(error))
    else:
        raise AssertionError(f"invalid rules were accepted: {candidate!r}")


assert_invalid({}, "non-empty mapping")
assert_invalid([], "non-empty mapping")
assert_invalid({"None": {}}, "reserved")
assert_invalid({"Label": {"unknown": 1}}, "unknown keys")
assert_invalid({"Label": {"rules": "text"}}, "must be a list")
assert_invalid({"Label": {"rules": [{"keywords": [False]}]}}, "Quote words")
assert_invalid({"Label": {"rules": [{"senders": "single.example"}]}}, "list of")
assert_invalid({"Label": {"rules": [{"sender": ["typo.example"]}]}}, "unknown keys")
assert_invalid({"Label": {"description": 5}}, "must be text")

# An unquoted `off` is read by YAML as a boolean: it must fail loudly.
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "rules.yaml"
    path.write_text(
        "Promotions:\n  rules:\n    - keywords:\n        - off\n", encoding="utf-8"
    )
    try:
        load_rules(path)
    except RulesError as error:
        assert "Quote words" in str(error)
    else:
        raise AssertionError("unquoted boolean keyword was accepted")

    path.write_text(
        'Promotions:\n  description: ok\n  rules:\n    - keywords:\n        - "off"\n',
        encoding="utf-8",
    )
    assert classify_email("a@b.example", "50% off", load_rules(path)) == "Promotions"

print("Classifier tests passed")
