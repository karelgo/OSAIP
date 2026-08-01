"""THE mesh pipeline (spec §5b, ADR-0008 §1).

    authz → CP-11 residency gate → guardrails `pre` (redact) → quota reserve
          → cache lookup (on the REDACTED payload) → provider
          → guardrails `post` → settle (ledger + audit + span)

The deviation from §5b's literal order (redaction ahead of cache/provider) is
deliberate and recorded in ADR-0008 §1: the literal order defeats its own acceptance
criterion, because a cache hit would skip redaction and store raw PII, and the cache
key would be computed over raw text.

Slice 2 wires the ledger, traces/spans, audit storage and cache; quotas (slice 3) and
guardrails/CP-11 (slice 4) fill in the marked seams.
"""

import datetime
import time
import uuid
from dataclasses import dataclass, field, replace
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from osaip_mesh.cache import cache_lookup, cache_store, compute_request_hash, is_cacheable
from osaip_mesh.cost import compute_cost
from osaip_mesh.ledger import LedgerEntry, ensure_trace, record_call, record_span
from osaip_mesh.providers.base import (
    CompletionRequest,
    CompletionResult,
    Message,
    Provider,
    ProviderError,
)


@dataclass
class ConnectionInfo:
    """The connection's settle-relevant configuration, decoupled from the ORM row so
    the pipeline can be unit-tested without a connection record."""

    id: uuid.UUID | None
    provider: str
    cache_ttl_s: int = 0
    audit_mode: str = "redacted"
    data_residency: str = "local"


@dataclass
class CallContext:
    """What the caller declares about this call. `max_classification` is mandatory for
    the CP-11 gate — a missing declaration fails closed (treated `bijzonder`)."""

    project_id: uuid.UUID | None = None
    user_id: uuid.UUID | None = None
    purpose: str = "general"
    max_classification: str = "bijzonder"
    trace_id: uuid.UUID | None = None
    job_id: uuid.UUID | None = None
    job_step_id: uuid.UUID | None = None
    row_key: str | None = None
    depth: int = 0
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class MeshOutcome:
    content: str
    tokens_in: int
    tokens_out: int
    cost_micros: int
    currency: str
    pricing_unknown: bool
    tokens_estimated: bool
    cache_hit: bool
    latency_ms: int
    model_version: str | None
    call_id: uuid.UUID | None = None
    trace_id: uuid.UUID | None = None
    guardrail_events: list[dict[str, Any]] = field(default_factory=list)


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


async def run_pipeline(
    *,
    session: AsyncSession,
    provider: Provider,
    connection: ConnectionInfo,
    request: CompletionRequest,
    context: CallContext,
) -> MeshOutcome:
    """Execute one model call through the mesh. Blocking work belongs in the stages;
    this function owns the ORDER, which is the part that must never drift."""
    started_at = _utcnow()
    started = time.perf_counter()

    # ── CP-11 residency gate lands in slice 4 ────────────────────────────────────
    # ── guardrails `pre` land in slice 4; until then redaction is the identity, but
    #    everything downstream already reads the REDACTED list, so switching the stage
    #    on cannot change the order. ────────────────────────────────────────────────
    raw_messages: list[Message] = list(request.messages)
    redacted_messages: list[Message] = [
        Message(role=m.role, content=m.content) for m in raw_messages
    ]
    # The provider is called with the redacted payload — that is the point of redacting
    # before the call, not merely before storage.
    provider_request = replace(request, messages=redacted_messages)

    request_hash = compute_request_hash(
        connection_id=connection.id,
        project_id=context.project_id,
        request=provider_request,
        redacted_messages=redacted_messages,
    )

    # ── quota reserve lands in slice 3 ───────────────────────────────────────────

    cacheable = is_cacheable(
        ttl_s=connection.cache_ttl_s, purpose=context.purpose, temperature=request.temperature
    )
    cached = await cache_lookup(session, request_hash) if cacheable else None

    # Release the read transaction BEFORE the provider round-trip: a mesh request must
    # never hold a DB transaction open across a network call to a model provider.
    await session.rollback()

    if cached is not None:
        result = CompletionResult(
            content=cached.content,
            tokens_in=cached.tokens_in,
            tokens_out=cached.tokens_out,
            model_version=cached.model_version,
            tokens_estimated=cached.tokens_estimated,
        )
        cost_micros, currency, pricing_unknown = 0, "EUR", False  # a hit spends nothing
    else:
        try:
            result = await _invoke(provider, provider_request)
        except ProviderError as exc:
            await _record_failure(
                session,
                connection=connection,
                context=context,
                request=provider_request,
                redacted_messages=redacted_messages,
                raw_messages=raw_messages,
                request_hash=request_hash,
                started_at=started_at,
                latency_ms=int((time.perf_counter() - started) * 1000),
                reason=exc.public_message,
            )
            raise
        cost = compute_cost(connection.provider, request.model, result.tokens_in, result.tokens_out)
        cost_micros, currency, pricing_unknown = (
            cost.cost_micros,
            cost.currency,
            cost.pricing_unknown,
        )

    # ── guardrails `post` land in slice 4 ────────────────────────────────────────
    answer = Message(role="assistant", content=result.content)
    audited_redacted = [*redacted_messages, answer]
    audited_raw = [*raw_messages, answer]

    latency_ms = int((time.perf_counter() - started) * 1000)
    finished_at = _utcnow()

    # ── settle ──────────────────────────────────────────────────────────────────
    trace_id = await ensure_trace(
        session,
        context.trace_id,
        root_kind="recipe" if context.job_id else "manual",
        project_id=context.project_id,
    )
    span = await record_span(
        session,
        trace_id=trace_id,
        name=f"{connection.provider}:{request.model}",
        started_at=started_at,
        finished_at=finished_at,
        tokens=result.tokens_in + result.tokens_out,
        cost_micros=cost_micros,
        # Span payloads follow the same rule as the audit: redacted text only.
        input_json={"model": request.model, "messages": len(redacted_messages)},
        output_json={"cache_hit": cached is not None},
    )
    call = await record_call(
        session,
        LedgerEntry(
            provider=connection.provider,
            model=request.model,
            model_version=result.model_version,
            purpose=context.purpose,
            tokens_in=result.tokens_in,
            tokens_out=result.tokens_out,
            tokens_estimated=result.tokens_estimated,
            cost_micros=cost_micros,
            currency=currency,
            pricing_unknown=pricing_unknown,
            latency_ms=latency_ms,
            cache_hit=cached is not None,
            project_id=context.project_id,
            user_id=context.user_id,
            connection_id=connection.id,
            trace_id=trace_id,
            span_id=span.span_id,
            job_id=context.job_id,
            job_step_id=context.job_step_id,
            row_key=context.row_key,
            request_hash=request_hash,
        ),
        messages_redacted=audited_redacted,
        messages_raw=audited_raw,
        audit_mode=connection.audit_mode,
    )
    if cacheable and cached is None:
        await cache_store(
            session,
            request_hash=request_hash,
            connection_id=connection.id,
            project_id=context.project_id,
            content=result.content,
            tokens_in=result.tokens_in,
            tokens_out=result.tokens_out,
            model_version=result.model_version,
            tokens_estimated=result.tokens_estimated,
            ttl_s=connection.cache_ttl_s,
        )
    await session.commit()

    return MeshOutcome(
        content=result.content,
        tokens_in=result.tokens_in,
        tokens_out=result.tokens_out,
        cost_micros=cost_micros,
        currency=currency,
        pricing_unknown=pricing_unknown,
        tokens_estimated=result.tokens_estimated,
        cache_hit=cached is not None,
        latency_ms=latency_ms,
        model_version=result.model_version,
        call_id=call.id,
        trace_id=trace_id,
    )


async def _invoke(provider: Provider, request: CompletionRequest) -> CompletionResult:
    """Every provider failure leaves the adapter as a ProviderError with a message that
    is safe to show — raw driver/HTTP text could carry the API key or an internal URL."""
    try:
        return await provider.complete(request)
    except ProviderError:
        raise
    except Exception as exc:
        raise ProviderError("The model provider could not be reached.") from exc


async def _record_failure(
    session: AsyncSession,
    *,
    connection: ConnectionInfo,
    context: CallContext,
    request: CompletionRequest,
    redacted_messages: list[Message],
    raw_messages: list[Message],
    request_hash: str,
    started_at: datetime.datetime,
    latency_ms: int,
    reason: str,
) -> None:
    """A failed call is still a call: it consumed a quota reservation and it belongs in
    the ledger, otherwise usage reporting silently under-counts provider trouble."""
    await session.rollback()
    trace_id = await ensure_trace(
        session,
        context.trace_id,
        root_kind="recipe" if context.job_id else "manual",
        project_id=context.project_id,
    )
    span = await record_span(
        session,
        trace_id=trace_id,
        name=f"{connection.provider}:{request.model}",
        started_at=started_at,
        finished_at=_utcnow(),
        tokens=0,
        cost_micros=0,
        status="error",
        # The sanitized public message only — never the raw provider text.
        output_json={"error": reason},
    )
    await record_call(
        session,
        LedgerEntry(
            provider=connection.provider,
            model=request.model,
            purpose=context.purpose,
            tokens_in=0,
            tokens_out=0,
            cost_micros=0,
            currency="EUR",
            latency_ms=latency_ms,
            status="error",
            project_id=context.project_id,
            user_id=context.user_id,
            connection_id=connection.id,
            trace_id=trace_id,
            span_id=span.span_id,
            job_id=context.job_id,
            job_step_id=context.job_step_id,
            row_key=context.row_key,
            request_hash=request_hash,
        ),
        messages_redacted=redacted_messages,
        messages_raw=raw_messages,
        audit_mode=connection.audit_mode,
    )
    await session.commit()


def messages_from_payload(payload: list[dict[str, str]]) -> list[Message]:
    return [Message(role=item["role"], content=item["content"]) for item in payload]
