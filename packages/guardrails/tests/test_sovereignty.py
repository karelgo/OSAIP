"""CP-11: which classifications may reach which residency, and failing closed."""

import pytest

from osaip_guardrails.sovereignty import (
    check_residency,
    is_allowed,
    normalise_classification,
    refusal_reason,
)
from osaip_guardrails.types import Action


@pytest.mark.parametrize(
    ("classification", "residency", "expected"),
    [
        # The BSN and special-category data never leave the local boundary.
        ("bsn", "local", True),
        ("bsn", "eu", False),
        ("bsn", "external", False),
        ("bijzonder", "local", True),
        ("bijzonder", "eu", False),
        ("bijzonder", "external", False),
        # Ordinary personal data may stay in the EU but not go further.
        ("persoonsgegevens", "local", True),
        ("persoonsgegevens", "eu", True),
        ("persoonsgegevens", "external", False),
        # Non-personal data routes anywhere.
        ("none", "local", True),
        ("none", "eu", True),
        ("none", "external", True),
    ],
)
def test_the_routing_matrix(classification: str, residency: str, expected: bool) -> None:
    assert is_allowed(classification, residency) is expected


@pytest.mark.parametrize("value", [None, "", "unknown", "TOP-SECRET", "None"])
def test_an_undeclared_classification_fails_closed(value: str | None) -> None:
    """Defaulting to `none` would give a caller who forgot to declare the most
    permissive routing — precisely backwards."""
    assert normalise_classification(value) == "bijzonder"
    assert is_allowed(value or "", "external") is False


def test_a_block_produces_an_event_naming_the_rule() -> None:
    allowed, event = check_residency(
        classification="bsn", residency="external", connection_name="openai-prod"
    )
    assert allowed is False
    assert event.rule == "cp11.residency"
    assert event.action is Action.BLOCK
    assert event.details["classification"] == "bsn"
    assert event.details["residency"] == "external"
    assert event.details["connection"] == "openai-prod"


def test_an_allowed_call_is_evented_too() -> None:
    """CP-11 accountability is about showing what was routed where, not only refusals."""
    allowed, event = check_residency(classification="none", residency="external")
    assert allowed is True
    assert event.action is Action.ALLOW


def test_every_event_says_residency_is_operator_asserted() -> None:
    """The platform enforces the declaration; it cannot verify geography. An audit
    reader must never be left thinking otherwise (ADR-0008 §7)."""
    _, event = check_residency(classification="bsn", residency="local")
    assert event.details["residency_is_operator_asserted"] is True


def test_the_refusal_says_what_to_change() -> None:
    reason = refusal_reason("bsn", "external")
    assert "bsn" in reason
    assert "local" in reason
    assert "external" in reason


def test_the_refusal_mentions_a_missing_declaration() -> None:
    reason = refusal_reason(None, "external")
    assert "no classification was declared" in reason
    assert "bijzonder" in reason
