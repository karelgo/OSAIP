"""Turning detections into redacted text."""

from collections import Counter

from osaip_guardrails.detectors import detect_all
from osaip_guardrails.types import Action, Detection, GuardrailEvent, StageResult


def apply_redactions(text: str, detections: list[Detection]) -> str:
    """Replace each detection with its placeholder, right to left so earlier offsets
    stay valid as the string changes length."""
    redacted = text
    for detection in sorted(detections, key=lambda d: d.start, reverse=True):
        redacted = redacted[: detection.start] + detection.placeholder + redacted[detection.end :]
    return redacted


def redact(text: str, *, stage: str = "pre", detector_label: str = "regex") -> StageResult:
    """Redact every deterministic detection.

    The event records COUNTS BY KIND, never the matched values — a guardrail log that
    quotes the BSN it found has simply moved the problem somewhere less guarded.
    """
    detections = detect_all(text)
    if not detections:
        return StageResult(text=text)

    counts = Counter(d.kind for d in detections)
    event = GuardrailEvent(
        stage=stage,
        rule=f"pii.{detector_label}",
        action=Action.REDACT,
        details={"counts": dict(sorted(counts.items())), "total": len(detections)},
    )
    return StageResult(text=apply_redactions(text, detections), events=[event])
