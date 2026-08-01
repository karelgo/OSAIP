"""The usage ledger, audit storage, and trace/span writes — the pipeline's "settle"
step (spec §4, §5b; ADR-0008 §8).

Ledger rows are plain inserts, deliberately OUTSIDE the hash-chained audit log's global
advisory lock: a per-row LLM build writes one row per input row, and taking the chain
lock for each would serialize every mutation on the platform. Only policy-relevant
events — a residency block, a quota block — go into the chained audit.

Message text is stored redacted ALWAYS; the raw variant only when the connection's
audit_mode is 'full'. audit_mode='off' stores no message rows at all.
"""

import datetime
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from osaip_api.models import LlmCall, LlmCallMessage, Span, Trace
from osaip_mesh.providers.base import Message
from osaip_shared.ids import new_id

AUDIT_MODES = ("full", "redacted", "off")


@dataclass
class LedgerEntry:
    """Everything the settle step records about one model call."""

    provider: str
    model: str
    purpose: str
    tokens_in: int
    tokens_out: int
    cost_micros: int
    currency: str
    latency_ms: int
    model_version: str | None = None
    tokens_estimated: bool = False
    pricing_unknown: bool = False
    cache_hit: bool = False
    status: str = "ok"
    project_id: uuid.UUID | None = None
    user_id: uuid.UUID | None = None
    connection_id: uuid.UUID | None = None
    trace_id: uuid.UUID | None = None
    span_id: uuid.UUID | None = None
    agent_id: uuid.UUID | None = None
    session_id: uuid.UUID | None = None
    job_id: uuid.UUID | None = None
    job_step_id: uuid.UUID | None = None
    row_key: str | None = None
    request_hash: str | None = None
    guardrail_events: list[dict[str, Any]] = field(default_factory=list)


async def record_call(
    session: AsyncSession,
    entry: LedgerEntry,
    *,
    messages_redacted: list[Message],
    messages_raw: list[Message] | None = None,
    audit_mode: str = "redacted",
) -> LlmCall:
    """Write the ledger row plus the audited messages.

    `messages_redacted` carries the prompt AND the assistant response, in order, so the
    audit shows what was actually sent and what came back. `messages_raw` is the
    pre-redaction parallel list and is only ever persisted under audit_mode='full'.
    """
    call = LlmCall(
        id=new_id(),
        project_id=entry.project_id,
        user_id=entry.user_id,
        agent_id=entry.agent_id,
        session_id=entry.session_id,
        trace_id=entry.trace_id,
        span_id=entry.span_id,
        job_id=entry.job_id,
        job_step_id=entry.job_step_id,
        row_key=entry.row_key,
        connection_id=entry.connection_id,
        provider=entry.provider,
        model=entry.model,
        model_version=entry.model_version,
        purpose=entry.purpose,
        tokens_in=entry.tokens_in,
        tokens_out=entry.tokens_out,
        tokens_estimated=entry.tokens_estimated,
        cost_micros=entry.cost_micros,
        currency=entry.currency,
        pricing_unknown=entry.pricing_unknown,
        latency_ms=entry.latency_ms,
        cache_hit=entry.cache_hit,
        status=entry.status,
        guardrail_events_json={"events": entry.guardrail_events},
        request_hash=entry.request_hash,
    )
    session.add(call)
    await session.flush()

    if audit_mode == "off":
        # Nothing is stored. Choosing 'off' is site-admin-only and the API layer audits
        # the change itself, so the absence of message rows stays an accountable choice.
        return call

    keep_raw = audit_mode == "full"
    for index, message in enumerate(messages_redacted):
        raw: str | None = None
        if keep_raw and messages_raw is not None and index < len(messages_raw):
            original = messages_raw[index].content
            # Only worth a second copy when redaction actually changed something.
            raw = original if original != message.content else None
        session.add(
            LlmCallMessage(
                id=new_id(),
                call_id=call.id,
                seq=index,
                role=message.role,
                content_redacted=message.content,
                content_raw=raw,
            )
        )
    await session.flush()
    return call


async def ensure_trace(
    session: AsyncSession,
    trace_id: uuid.UUID | None,
    *,
    root_kind: str = "manual",
    project_id: uuid.UUID | None = None,
) -> uuid.UUID:
    """Return a trace id, creating the root when the caller did not supply one. A
    caller that already owns a trace (a build step) passes it, so its spans nest.

    ON CONFLICT DO NOTHING rather than check-then-insert: a per-row LLM build fires many
    concurrent calls that all share one caller-supplied trace_id, and a read followed by
    an insert lets two of them both see "absent" and one die on the primary key — inside
    the settle transaction, which would lose an already-billed call.
    """
    new_trace_id = trace_id or new_id()
    await session.execute(
        pg_insert(Trace)
        .values(trace_id=new_trace_id, root_kind=root_kind, project_id=project_id)
        .on_conflict_do_nothing(index_elements=[Trace.trace_id])
    )
    return new_trace_id


async def record_span(
    session: AsyncSession,
    *,
    trace_id: uuid.UUID,
    name: str,
    started_at: datetime.datetime,
    finished_at: datetime.datetime,
    tokens: int,
    cost_micros: int,
    parent_id: uuid.UUID | None = None,
    status: str = "ok",
    input_json: dict[str, Any] | None = None,
    output_json: dict[str, Any] | None = None,
) -> Span:
    """One `llm` span per mesh call. The Trace Explorer UI lands in P6; the spans it
    will read start accumulating now (spec §5b)."""
    span = Span(
        span_id=new_id(),
        trace_id=trace_id,
        parent_id=parent_id,
        kind="llm",
        name=name,
        input_json=input_json,
        output_json=output_json,
        tokens=tokens,
        cost_micros=cost_micros,
        t0=started_at,
        t1=finished_at,
        status=status,
    )
    session.add(span)
    # Rollups are computed in SQL so concurrent spans on one trace cannot lose a count.
    await session.execute(
        update(Trace)
        .where(Trace.trace_id == trace_id)
        .values(
            span_count=Trace.span_count + 1,
            total_cost_micros=Trace.total_cost_micros + cost_micros,
        )
    )
    await session.flush()
    return span
