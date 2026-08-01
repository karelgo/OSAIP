"""Deterministic detectors: checksums, and the false positives they exist to avoid.

A redactor is judged in both directions. Missing a real BSN is a data-protection
incident; flagging every nine-digit order number is how a redactor gets switched off.
"""

import pytest

from osaip_guardrails.detectors import (
    detect_all,
    find_bsn,
    find_email,
    find_iban,
    find_phone,
    is_valid_bsn,
    is_valid_iban,
)
from osaip_guardrails.redact import redact

# Checksum-valid BSNs (synthetic — these are test vectors, not anyone's number).
VALID_BSN = ["111222333", "123456782", "999999990"]
# Nine digits that FAIL the 11-proef: a bare \d{9} regex would flag every one of these.
INVALID_BSN = ["123456789", "111111111", "000000000", "123456780"]


@pytest.mark.parametrize("value", VALID_BSN)
def test_valid_bsn_passes_the_11_proef(value: str) -> None:
    assert is_valid_bsn(value) is True


@pytest.mark.parametrize("value", INVALID_BSN)
def test_invalid_bsn_is_rejected(value: str) -> None:
    assert is_valid_bsn(value) is False


def test_eight_digit_sofinummer_is_padded() -> None:
    """A legacy 8-digit number is a BSN with its leading zero dropped, and must
    validate the same either way."""
    assert is_valid_bsn("10000008") is True
    assert is_valid_bsn("010000008") is True


@pytest.mark.parametrize("value", ["", "12345", "abcdefghi", "1234567890123"])
def test_non_bsn_shapes_are_rejected(value: str) -> None:
    assert is_valid_bsn(value) is False


def test_bsn_inside_a_longer_digit_run_is_not_matched() -> None:
    """A 13-digit id contains 9-digit substrings; none of them is a BSN."""
    assert find_bsn("order 1112223334444") == []


def test_bsn_next_to_letters_is_still_found() -> None:
    assert len(find_bsn("case id42:111222333 closed")) == 1


@pytest.mark.parametrize(
    "value",
    ["NL91ABNA0417164300", "NL91 ABNA 0417 1643 00", "DE89370400440532013000"],
)
def test_valid_iban_passes_mod_97(value: str) -> None:
    assert is_valid_iban(value) is True


@pytest.mark.parametrize(
    "value",
    ["NL91ABNA0417164301", "NL00ABNA0417164300", "XX91ABNA0417164300", "NL91"],
)
def test_invalid_iban_is_rejected(value: str) -> None:
    assert is_valid_iban(value) is False


def test_iban_is_detected_in_running_text() -> None:
    found = find_iban("Betaal naar NL91 ABNA 0417 1643 00 graag.")
    assert len(found) == 1


@pytest.mark.parametrize("value", ["jan@example.nl", "j.de.vries+werk@uwv.example.com", "a_b@x.co"])
def test_emails_are_found(value: str) -> None:
    assert len(find_email(f"mail {value} please")) == 1


@pytest.mark.parametrize("value", ["not-an-email", "@example.nl", "a@b"])
def test_non_emails_are_not_found(value: str) -> None:
    assert find_email(value) == []


@pytest.mark.parametrize(
    "value", ["0612345678", "06-12345678", "+31612345678", "+31 6 12345678", "0201234567"]
)
def test_dutch_phone_numbers_are_found(value: str) -> None:
    assert len(find_phone(f"bel {value} maar")) == 1


# ── overlap handling ─────────────────────────────────────────────────────────────


def test_overlapping_detections_do_not_fragment_each_other() -> None:
    """A phone-shaped run inside an email must not split the email in two."""
    detections = detect_all("mail 0612345678@example.nl nu")
    assert [d.kind for d in detections] == ["email"]


def test_bsn_wins_over_phone_for_the_same_digits() -> None:
    """Labelling a national identifier as a phone number would under-state it."""
    detections = detect_all("nummer 111222333")
    assert [d.kind for d in detections] == ["bsn"]


# ── redaction ────────────────────────────────────────────────────────────────────


def test_redaction_replaces_every_match() -> None:
    result = redact("BSN 111222333 en IBAN NL91ABNA0417164300 en jan@example.nl")
    assert "111222333" not in result.text
    assert "NL91ABNA0417164300" not in result.text
    assert "jan@example.nl" not in result.text
    assert "<BSN>" in result.text and "<IBAN>" in result.text and "<EMAIL>" in result.text


def test_redaction_keeps_the_surrounding_text_intact() -> None:
    result = redact("De klant met BSN 111222333 belde vandaag.")
    assert result.text == "De klant met BSN <BSN> belde vandaag."


def test_clean_text_is_untouched_and_uneventful() -> None:
    result = redact("Wat is het weer vandaag?")
    assert result.text == "Wat is het weer vandaag?"
    assert result.events == []


def test_the_event_counts_but_never_quotes_the_value() -> None:
    """A guardrail log that quotes the BSN it found has moved the problem, not solved it."""
    result = redact("BSN 111222333 en 123456782")
    event = result.events[0]
    assert event.details["counts"] == {"bsn": 2}
    assert "111222333" not in str(event.as_dict())


def test_multiple_matches_of_one_kind_all_go() -> None:
    result = redact("111222333 / 123456782 / 999999990")
    assert result.text == "<BSN> / <BSN> / <BSN>"
