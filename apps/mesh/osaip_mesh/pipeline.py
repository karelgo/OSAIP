"""THE mesh pipeline (spec §5b, ADR-0008 §1).

    authz → CP-11 residency gate → guardrails `pre` (redact) → quota reserve
          → cache lookup (on the REDACTED payload) → provider
          → guardrails `post` → settle (ledger + audit + span)

The deviation from §5b's literal order (redaction ahead of cache/provider) is
deliberate and recorded in ADR-0008 §1: the literal order defeats its own acceptance
criterion, because a cache hit would skip redaction and store raw PII, and the cache
key would be computed over raw text.

Quota reserve/settle brackets the provider call: the hold is committed before the call
so concurrent callers can see it, and settles to the actual cost in the same transaction
as the ledger row. Guardrails and the CP-11 gate (slice 4) fill in the marked seams.
"""

import datetime
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from osaip_api.notifications import notify
from osaip_guardrails.policy import BASELINE, PolicyConfig
from osaip_mesh.cache import cache_lookup, cache_store, compute_request_hash, is_cacheable
from osaip_mesh.cost import compute_cost, estimate_tokens
from osaip_mesh.guardrails import (
    enforce_residency,
    events_payload,
    persist_events,
    run_post_stage,
    run_pre_stage,
)
from osaip_mesh.ledger import LedgerEntry, ensure_trace, record_call, record_span
from osaip_mesh.providers.base import (
    CompletionRequest,
    CompletionResult,
    Message,
    Provider,
    ProviderError,
)
from osaip_mesh.quotas import QuotaStatus, Reservation, Scope, reserve, settle


@dataclass
class ConnectionInfo:
    """The connection's settle-relevant configuration, decoupled from the ORM row so
    the pipeline can be unit-tested without a connection record."""

    id: uuid.UUID | None
    provider: str
    cache_ttl_s: int = 0
    audit_mode: str = "redacted"
    data_residency: str = "local"
    name: str | None = None
    # Already merged with the non-removable baseline (osaip_guardrails.policy).
    policy: PolicyConfig = BASELINE


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
    quota_warnings: list[dict[str, Any]] = field(default_factory=list)


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


async def run_pipeline(
    *,
    session: AsyncSession,
    make_provider: Callable[[], Provider],
    connection: ConnectionInfo,
    request: CompletionRequest,
    context: CallContext,
) -> MeshOutcome:
    """Execute one model call through the mesh. Blocking work belongs in the stages;
    this function owns the ORDER, which is the part that must never drift.

    The provider is built by a FACTORY rather than passed in, so that constructing it
    (which can fail on bad config or an SSRF-rejected URL, and used to happen in the
    router) cannot preempt the CP-11 gate. A sovereignty refusal must be recorded as a
    sovereignty refusal, not reported as a configuration error.
    """
    started_at = _utcnow()
    started = time.perf_counter()

    # ── CP-11 residency gate: before any redaction, because the question "may this
    #    class of data go to this endpoint at all?" is not softened by redacting it ──
    residency_event = await enforce_residency(
        session,
        classification=context.max_classification,
        residency=connection.data_residency,
        project_id=context.project_id,
        user_id=context.user_id,
        connection_id=connection.id,
        connection_name=connection.name,
    )

    # ── guardrails `pre` (redact) ────────────────────────────────────────────────
    raw_messages: list[Message] = list(request.messages)
    pre = await run_pre_stage(raw_messages, connection.policy)
    redacted_messages = pre.messages
    guardrail_events = [residency_event, *pre.events]
    # The provider is called with the redacted payload — that is the point of redacting
    # before the call, not merely before storage.
    provider_request = replace(request, messages=redacted_messages)

    # Built only now: after the gate, before any budget is held.
    provider = make_provider()

    request_hash = compute_request_hash(
        connection_id=connection.id,
        project_id=context.project_id,
        request=provider_request,
        redacted_messages=redacted_messages,
    )

    # ── quota reserve (commits, so the hold is visible to concurrent callers) ────
    reservation = await reserve(
        session,
        scopes=_scopes(connection, context),
        estimated_micros=_worst_case_micros(connection.provider, provider_request),
    )

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
                reservation=reservation,
            )
            raise
        cost = compute_cost(connection.provider, request.model, result.tokens_in, result.tokens_out)
        cost_micros, currency, pricing_unknown = (
            cost.cost_micros,
            cost.currency,
            cost.pricing_unknown,
        )

    # ── guardrails `post`: validate the shape, redact the copy we store ─────────
    audited_answer, post_events = run_post_stage(result.content, connection.policy)
    guardrail_events.extend(post_events)
    audited_redacted = [*redacted_messages, Message(role="assistant", content=audited_answer)]
    audited_raw = [*raw_messages, Message(role="assistant", content=result.content)]

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
            guardrail_events=events_payload(guardrail_events),
        ),
        messages_redacted=audited_redacted,
        messages_raw=audited_raw,
        audit_mode=connection.audit_mode,
    )
    persist_events(session, guardrail_events, call_id=call.id, project_id=context.project_id)
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
    # The hold shrinks to the truth — 0 for a cache hit — in the same transaction as
    # the ledger row, so spend and reservation can never disagree.
    await settle(session, reservation, actual_micros=cost_micros, call_id=call.id)
    await _notify_crossings(session, reservation, user_id=context.user_id)
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
        guardrail_events=events_payload(guardrail_events),
        quota_warnings=[_warning_payload(w) for w in reservation.warnings],
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
    reservation: Reservation,
) -> None:
    """A failed call is still a call: it belongs in the ledger, otherwise usage
    reporting silently under-counts provider trouble. Its reservation settles to 0 —
    a failure must not keep consuming budget."""
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
    await settle(session, reservation, actual_micros=0, call_id=None)
    await session.commit()


def _scopes(connection: ConnectionInfo, context: CallContext) -> list[Scope]:
    """Every budget this call is subject to. A call can be under several at once (its
    project, its user, its connection); all of them must have room."""
    scopes = []
    if context.project_id is not None:
        scopes.append(Scope("project", context.project_id))
    if context.user_id is not None:
        scopes.append(Scope("user", context.user_id))
    if connection.id is not None:
        scopes.append(Scope("connection", connection.id))
    return scopes


def _worst_case_micros(provider_name: str, request: CompletionRequest) -> int:
    """What this call could cost if the model emits every token it is allowed to. The
    reservation is deliberately pessimistic; settle replaces it with the truth."""
    prompt_tokens = sum(estimate_tokens(m.content) for m in request.messages)
    return compute_cost(provider_name, request.model, prompt_tokens, request.max_tokens).cost_micros


async def _notify_crossings(
    session: AsyncSession, reservation: Reservation, *, user_id: uuid.UUID | None
) -> None:
    """Tell someone the first time a warn budget goes over. A warn budget keeps letting
    calls through, so without the once-only guard this would notify on every call."""
    if user_id is None:
        return
    for status in reservation.warnings:
        if not status.just_crossed:
            continue
        await notify(
            session,
            user_id=user_id,
            kind="quota.warning",
            severity="warning",
            title=f"{status.scope_type.capitalize()} budget exceeded",
            body=(
                f"The {status.period} {status.exceeded_dimension} budget is over its "
                f"limit. Calls still go through — this budget is set to warn, not block."
            ),
            ref_kind="quota",
            ref_id=str(status.scope_id),
        )


def _warning_payload(status: QuotaStatus) -> dict[str, Any]:
    return {
        "scope_type": status.scope_type,
        "scope_id": str(status.scope_id),
        "period": status.period,
        "dimension": status.exceeded_dimension,
        "spent_micros": status.spent_micros,
        "limit_cost_micros": status.limit_cost_micros,
        "limit_calls": status.limit_calls,
        "window_start": status.window_start.isoformat(),
    }


def messages_from_payload(payload: list[dict[str, str]]) -> list[Message]:
    return [Message(role=item["role"], content=item["content"]) for item in payload]
