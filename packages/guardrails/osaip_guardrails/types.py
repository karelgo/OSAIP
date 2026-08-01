"""Guardrail stage vocabulary.

A stage inspects a payload and returns a verdict. Stages never mutate their input in
place: redaction returns new text, so the caller keeps the original and decides — per
the connection's audit_mode — whether it is allowed to persist it.
"""

import enum
from dataclasses import dataclass, field
from typing import Any, Protocol


class Action(enum.StrEnum):
    ALLOW = "allow"
    REDACT = "redact"
    BLOCK = "block"


@dataclass(frozen=True)
class Detection:
    """One match in a piece of text. Offsets are into the string that was scanned."""

    kind: str  # bsn | iban | email | phone | …
    start: int
    end: int
    detector: str  # which layer found it — "regex" or "presidio"
    score: float = 1.0

    @property
    def placeholder(self) -> str:
        return f"<{self.kind.upper()}>"


@dataclass
class GuardrailEvent:
    """A record of what a stage did, destined for `guardrail_events` and the ledger."""

    stage: str  # pre | post
    rule: str
    action: Action
    details: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "rule": self.rule,
            "action": str(self.action),
            "details": self.details,
        }


@dataclass
class StageResult:
    """What a stage decided.

    `blocked` carries a reason the user is allowed to see: a guardrail block must be
    explainable ("this contains a BSN and this connection is not local"), never an
    opaque refusal.
    """

    text: str
    events: list[GuardrailEvent] = field(default_factory=list)
    blocked: bool = False
    reason: str | None = None


class Stage(Protocol):
    """Stages compose in a fixed order; each sees the previous stage's output."""

    name: str

    def run(self, text: str, context: dict[str, Any]) -> StageResult: ...


class GuardrailBlocked(Exception):
    """A stage refused the payload. The message is user-facing by construction."""

    def __init__(
        self, reason: str, *, rule: str, events: list[GuardrailEvent] | None = None
    ) -> None:
        super().__init__(reason)
        self.reason = reason
        self.rule = rule
        self.events = events or []
