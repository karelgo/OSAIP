"""Mesh-side adapter for `packages/guardrails`: runs the stages over a message list and
persists what they did.

The package holds the rules (they are testable without a database); this module holds
the wiring — which text gets scanned, and how a decision reaches `guardrail_events`, the
ledger and, for policy-relevant refusals, the hash-chained audit.
"""

import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from osaip_api.audit import write_audit
from osaip_api.models import GuardrailEvent as GuardrailEventRow
from osaip_guardrails.policy import PolicyConfig, run_post, run_pre
from osaip_guardrails.sovereignty import check_residency, refusal_reason
from osaip_guardrails.types import GuardrailEvent
from osaip_mesh.providers.base import Message
from osaip_shared.ids import new_id


class ResidencyBlocked(Exception):
    """CP-11 refused this route. Carries text the caller may show a user: a block that
    cannot be explained is indistinguishable from a bug."""

    def __init__(self, reason: str, *, classification: str, residency: str) -> None:
        super().__init__(reason)
        self.reason = reason
        self.classification = classification
        self.residency = residency


class InputRejected(Exception):
    """A `pre` stage refused the payload (e.g. over the policy's length limit)."""

    def __init__(self, reason: str, *, events: list[GuardrailEvent]) -> None:
        super().__init__(reason)
        self.reason = reason
        self.events = events


@dataclass
class PreResult:
    messages: list[Message]
    events: list[GuardrailEvent] = field(default_factory=list)


async def enforce_residency(
    session: AsyncSession,
    *,
    classification: str,
    residency: str,
    project_id: uuid.UUID | None,
    user_id: uuid.UUID | None,
    connection_id: uuid.UUID | None,
    connection_name: str | None = None,
) -> GuardrailEvent:
    """The CP-11 gate. A refusal is persisted BEFORE it is raised, so a blocked attempt
    leaves a trail even though no model call and no ledger row will ever exist for it.
    """
    allowed, event = check_residency(
        classification=classification, residency=residency, connection_name=connection_name
    )
    if allowed:
        return event

    session.add(
        GuardrailEventRow(
            id=new_id(),
            call_id=None,  # there is no call: the gate ran before one could be made
            project_id=project_id,
            stage=event.stage,
            rule=event.rule,
            action=str(event.action),
            details=event.details,
        )
    )
    # A sovereignty refusal is policy-relevant, so unlike an ordinary ledger row it goes
    # into the hash-chained audit — and, per the audit contract, as the last write.
    await write_audit(
        session,
        actor_id=user_id,
        project_id=project_id,
        action="llm.residency_blocked",
        object_kind="llm_connection",
        object_id=str(connection_id) if connection_id else None,
        details=event.details,
    )
    await session.commit()
    raise ResidencyBlocked(
        refusal_reason(classification, residency),
        classification=event.details["classification"],
        residency=residency,
    )


def run_pre_stage(messages: list[Message], policy: PolicyConfig) -> PreResult:
    """Redact every message. Each message is scanned independently so an offset in one
    can never shift another, and the role is preserved so the provider still sees the
    conversation it was given."""
    redacted: list[Message] = []
    events: list[GuardrailEvent] = []
    for message in messages:
        result = run_pre(message.content, policy)
        if result.blocked:
            raise InputRejected(result.reason or "The prompt was rejected.", events=result.events)
        events.extend(result.events)
        redacted.append(Message(role=message.role, content=result.text))
    return PreResult(messages=redacted, events=events)


class OutputRejected(Exception):
    """A `post` stage refused the response — a schema mismatch, or a judge verdict.
    The call still happened and is still ledgered; what is withheld is the answer."""

    def __init__(self, reason: str, *, events: list[GuardrailEvent]) -> None:
        super().__init__(reason)
        self.reason = reason
        self.events = events


def run_post_stage(answer: str, policy: PolicyConfig) -> tuple[str, list[GuardrailEvent]]:
    """Returns the text to AUDIT plus the events. The caller still receives the model's
    actual answer; redaction here changes what the platform writes down, not what was
    said."""
    result = run_post(answer, policy)
    if result.blocked:
        raise OutputRejected(result.reason or "The response was rejected.", events=result.events)
    return result.text, result.events


def persist_events(
    session: AsyncSession,
    events: list[GuardrailEvent],
    *,
    call_id: uuid.UUID | None,
    project_id: uuid.UUID | None,
) -> None:
    for event in events:
        session.add(
            GuardrailEventRow(
                id=new_id(),
                call_id=call_id,
                project_id=project_id,
                stage=event.stage,
                rule=event.rule,
                action=str(event.action),
                details=event.details,
            )
        )


def events_payload(events: list[GuardrailEvent]) -> list[dict[str, Any]]:
    return [event.as_dict() for event in events]
