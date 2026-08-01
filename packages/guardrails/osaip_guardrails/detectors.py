"""Deterministic PII detectors — the layer that must work with no model, no network,
and no download (ADR-0008 §5).

Every detector here is checksum- or format-verified rather than "looks like". A bare
nine-digit regex would flag order numbers, case ids and timestamps as BSNs; the 11-proef
cuts that by roughly a factor of eleven, and mod-97 does the same for IBANs. That
matters in both directions: a redactor that cries wolf gets switched off, and one that
misses a real BSN is a data-protection incident.
"""

import re

from osaip_guardrails.types import Detection

# Not \b: a BSN adjoining a letter (id42:123456782) is still a BSN, but one inside a
# longer digit run (0123456782345) is not a BSN, it is a different number.
_BSN_RE = re.compile(r"(?<!\d)(\d{8,9})(?!\d)")
_IBAN_RE = re.compile(
    r"(?<![A-Z0-9])([A-Z]{2}\d{2}[ ]?(?:[A-Z0-9]{4}[ ]?){2,7}[A-Z0-9]{1,4})(?![A-Z0-9])"
)
_EMAIL_RE = re.compile(r"(?<![\w.+-])([\w.+-]+@[\w-]+\.[\w.-]{2,})(?![\w.-])")
# Dutch numbers, mobile and landline, in the shapes people actually type them.
_PHONE_RE = re.compile(
    r"(?<![\d+])("
    r"(?:\+31[ -]?\(?0?\)?|0031[ -]?|0)"  # +31, 0031, or a national leading 0
    r"(?:6[ -]?\d{8}|[1-9]\d[ -]?\d{7}|[1-9]\d{2}[ -]?\d{6})"  # mobile / 2- / 3-digit area
    r")(?!\d)"
)


def is_valid_bsn(digits: str) -> bool:
    """The Dutch 11-proef: 9*d1 + 8*d2 + … + 2*d8 - d9 must be divisible by 11.

    The final digit is subtracted, not added — that is the whole point of the check, and
    getting it wrong turns the validator into an accept-almost-anything filter.
    """
    if not digits.isdigit() or not 8 <= len(digits) <= 9:
        return False
    padded = digits.zfill(9)  # legacy 8-digit sofinummers are a BSN with a leading zero
    if padded == "0" * 9:
        return False
    total = sum(int(d) * (9 - i) for i, d in enumerate(padded[:8])) - int(padded[8])
    return total % 11 == 0


def is_valid_iban(candidate: str) -> bool:
    """ISO 13616 mod-97: move the first four characters to the end, map letters to
    numbers (A=10 … Z=35), and the whole thing mod 97 must equal 1."""
    compact = candidate.replace(" ", "").upper()
    if not 15 <= len(compact) <= 34 or not compact[:2].isalpha() or not compact[2:4].isdigit():
        return False
    if not compact.isalnum():
        return False
    rearranged = compact[4:] + compact[:4]
    digits = "".join(str(int(c, 36)) for c in rearranged)
    return int(digits) % 97 == 1


def _scan(text: str, pattern: re.Pattern[str], kind: str) -> list[Detection]:
    return [
        Detection(kind=kind, start=m.start(1), end=m.end(1), detector="regex")
        for m in pattern.finditer(text)
    ]


def find_bsn(text: str) -> list[Detection]:
    return [
        Detection(kind="bsn", start=m.start(1), end=m.end(1), detector="regex")
        for m in _BSN_RE.finditer(text)
        if is_valid_bsn(m.group(1))
    ]


def find_iban(text: str) -> list[Detection]:
    return [
        Detection(kind="iban", start=m.start(1), end=m.end(1), detector="regex")
        for m in _IBAN_RE.finditer(text)
        if is_valid_iban(m.group(1))
    ]


def find_email(text: str) -> list[Detection]:
    return _scan(text, _EMAIL_RE, "email")


def find_phone(text: str) -> list[Detection]:
    return _scan(text, _PHONE_RE, "phone")


# Order matters: BSN first so a nine-digit BSN is never claimed by the phone detector,
# which would label a national identifier as a mere phone number.
DETECTORS = (find_bsn, find_iban, find_email, find_phone)


def detect_all(text: str) -> list[Detection]:
    """Every detection, de-overlapped, in document order.

    Overlaps are resolved by earliest start then longest match, so a phone number that
    starts inside an email address cannot split the email into fragments.
    """
    found: list[Detection] = []
    for detector in DETECTORS:
        found.extend(detector(text))
    found.sort(key=lambda d: (d.start, -(d.end - d.start)))

    kept: list[Detection] = []
    cursor = -1
    for detection in found:
        if detection.start >= cursor:
            kept.append(detection)
            cursor = detection.end
    return kept
