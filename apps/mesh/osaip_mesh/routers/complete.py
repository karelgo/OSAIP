"""`POST /v1/complete` — the one entry point for a model call.

`/v1/stream` is deliberately absent in 3a: nothing consumes streams yet, and streaming
needs a post-guardrail design (you cannot unsend tokens) that belongs with the first
streaming consumer — recorded in docs/plans/phase-3a.md.
"""

import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from osaip_api.db import get_session
from osaip_api.models import GuardrailPolicy, LlmConnection, Secret
from osaip_api.problem import Problem
from osaip_guardrails.policy import merge_policy
from osaip_mesh.guardrails import InputRejected, OutputRejected, ResidencyBlocked
from osaip_mesh.pipeline import (
    CallContext,
    ConnectionInfo,
    MeshOutcome,
    messages_from_payload,
    run_pipeline,
)
from osaip_mesh.providers.base import CompletionRequest, ProviderError
from osaip_mesh.providers.echo import EchoProvider
from osaip_mesh.providers.litellm_provider import LiteLLMProvider
from osaip_mesh.quotas import QuotaExceeded

router = APIRouter(prefix="/v1", tags=["mesh"])

DbSession = Annotated[AsyncSession, Depends(get_session)]

CLASSIFICATIONS = ("none", "persoonsgegevens", "bijzonder", "bsn")


class MessageIn(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str = Field(max_length=1_000_000)


class CompleteIn(BaseModel):
    connection_id: uuid.UUID
    model: str = Field(min_length=1, max_length=200)
    messages: list[MessageIn] = Field(min_length=1)
    max_tokens: int = Field(default=512, ge=1, le=200_000)
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    purpose: str = Field(default="general", max_length=50)
    # CP-11: callers MUST declare the maximum classification of what they are sending.
    # Omitting it fails closed — the default is the strict end, not the lax one.
    max_classification: Literal["none", "persoonsgegevens", "bijzonder", "bsn"] = "bijzonder"
    project_id: uuid.UUID | None = None
    user_id: uuid.UUID | None = None
    trace_id: uuid.UUID | None = None
    job_id: uuid.UUID | None = None
    job_step_id: uuid.UUID | None = None
    row_key: str | None = Field(default=None, max_length=255)
    depth: int = Field(default=0, ge=0, le=4)


class CompleteOut(BaseModel):
    content: str
    tokens_in: int
    tokens_out: int
    tokens_estimated: bool
    cost_micros: int
    currency: str
    pricing_unknown: bool
    cache_hit: bool
    latency_ms: int
    model_version: str | None
    call_id: str | None
    trace_id: str | None
    guardrail_events: list[dict[str, Any]] = []
    # Budgets set to `warn` let the call through and report here; `block` never gets
    # this far — it raises a 429 instead.
    quota_warnings: list[dict[str, Any]] = []


async def _load_connection(session: AsyncSession, connection_id: uuid.UUID) -> LlmConnection:
    connection = (
        await session.execute(
            select(LlmConnection).where(
                LlmConnection.id == connection_id, LlmConnection.status == "active"
            )
        )
    ).scalar_one_or_none()
    if connection is None:
        raise Problem(
            404,
            title="LLM connection not found",
            detail="No such active LLM connection.",
            hint="Check the connection id.",
            slug="not-found",
        )
    return connection


async def _policy_stages(session: AsyncSession, connection: LlmConnection) -> dict[str, Any] | None:
    """A connection without a policy still gets the baseline — `merge_policy(None)`
    returns it. There is no configuration that yields no guardrails."""
    if connection.guardrail_policy_id is None:
        return None
    policy = (
        await session.execute(
            select(GuardrailPolicy).where(GuardrailPolicy.id == connection.guardrail_policy_id)
        )
    ).scalar_one_or_none()
    return policy.stages if policy is not None else None


async def _secret_for(session: AsyncSession, vault: Any, connection: LlmConnection) -> str | None:
    if connection.secret_id is None:
        return None
    secret = (
        await session.execute(select(Secret).where(Secret.id == connection.secret_id))
    ).scalar_one()
    value: str = vault.decrypt(secret.ciphertext)
    return value


def _build_provider(connection: LlmConnection, secret: str | None) -> Any:
    if connection.provider == "echo":
        if connection.data_residency != "local":
            # A mock must never stand in for a real external provider (ADR-0008 §9).
            raise Problem(
                422,
                title="Echo connection must be local",
                detail="The echo provider is a mock and only permits data_residency='local'.",
                hint="Set the connection's residency to local, or pick a real provider.",
                slug="validation",
            )
        return EchoProvider(connection.base_config, secret)
    # Every real provider goes through the one LiteLLM adapter, so openai-compatible,
    # anthropic and ollama connections share a single code path with echo (§5b).
    return LiteLLMProvider(connection.provider, connection.base_config, secret)


@router.post("/complete", response_model=CompleteOut)
async def complete(
    body: CompleteIn, request: Request, response: Response, session: DbSession
) -> dict[str, Any]:
    connection = await _load_connection(session, body.connection_id)
    if connection.allowed_models and body.model not in connection.allowed_models:
        raise Problem(
            422,
            title="Model not allowed",
            detail=f"{body.model!r} is not in this connection's allowlist.",
            hint=f"Allowed: {', '.join(connection.allowed_models)}.",
            slug="model-not-allowed",
        )
    secret = await _secret_for(session, request.app.state.vault, connection)

    context = CallContext(
        project_id=body.project_id,
        user_id=body.user_id,
        purpose=body.purpose,
        max_classification=body.max_classification,
        trace_id=body.trace_id,
        job_id=body.job_id,
        job_step_id=body.job_step_id,
        row_key=body.row_key,
        depth=body.depth,
    )
    completion = CompletionRequest(
        model=body.model,
        messages=messages_from_payload([m.model_dump() for m in body.messages]),
        max_tokens=body.max_tokens,
        temperature=body.temperature,
    )
    info = ConnectionInfo(
        id=connection.id,
        provider=connection.provider,
        cache_ttl_s=connection.cache_ttl_s,
        audit_mode=connection.audit_mode,
        data_residency=connection.data_residency,
        name=connection.name,
        policy=merge_policy(await _policy_stages(session, connection)),
    )
    try:
        outcome: MeshOutcome = await run_pipeline(
            session=session,
            # A factory, so provider construction happens inside the pipeline — after
            # the CP-11 gate, never before it.
            make_provider=lambda: _build_provider(connection, secret),
            connection=info,
            request=completion,
            context=context,
        )
    except ResidencyBlocked as exc:
        # 403, not 422: this is not a malformed request, it is a refusal to route this
        # class of data to this endpoint at all (CP-11).
        raise Problem(
            403,
            title="Blocked by data sovereignty policy",
            detail=exc.reason,
            hint="Route this call to a connection whose data residency is local, or "
            "lower the declared classification if the payload really is less sensitive.",
            slug="residency-blocked",
            extra={"classification": exc.classification, "data_residency": exc.residency},
        ) from exc
    except InputRejected as exc:
        raise Problem(
            422,
            title="Prompt rejected by guardrails",
            detail=exc.reason,
            hint="Shorten the prompt or relax the connection's guardrail policy.",
            slug="guardrail-input",
            extra={"guardrail_events": [e.as_dict() for e in exc.events]},
        ) from exc
    except OutputRejected as exc:
        raise Problem(
            422,
            title="Response rejected by guardrails",
            detail=exc.reason,
            hint="The model did not produce the shape this connection's policy requires.",
            slug="guardrail-output",
            extra={"guardrail_events": [e.as_dict() for e in exc.events]},
        ) from exc
    except QuotaExceeded as exc:
        status = exc.status
        # 429 like a provider rate-limit, but a DIFFERENT slug: being out of budget is
        # not something a retry fixes, and callers must be able to tell them apart.
        raise Problem(
            429,
            title="Quota exceeded",
            detail=(
                f"The {status.scope_type} {status.period} budget for "
                f"{status.exceeded_dimension} is exhausted."
            ),
            hint="Raise the budget in project settings, or wait for the window to reset.",
            slug="quota-exceeded",
            extra={
                "scope_type": status.scope_type,
                "scope_id": str(status.scope_id),
                "period": status.period,
                "window_start": status.window_start.isoformat(),
                "dimension": status.exceeded_dimension,
                "spent_micros": status.spent_micros,
                "limit_cost_micros": status.limit_cost_micros,
                "limit_calls": status.limit_calls,
            },
        ) from exc
    except ProviderError as exc:
        raise Problem(
            502,
            title="Model call failed",
            detail=exc.public_message,  # sanitized by the adapter — never raw HTTP text
            hint="Check the connection settings, or retry if the provider is rate-limiting.",
            slug="provider-rate-limited" if exc.retryable else "provider-failed",
        ) from exc

    if outcome.quota_warnings:
        # A header too, so a proxy or a non-JSON-reading caller still sees it.
        response.headers["X-OSAIP-Quota-Warning"] = ", ".join(
            f"{w['scope_type']}:{w['dimension']}" for w in outcome.quota_warnings
        )
    return {
        "content": outcome.content,
        "tokens_in": outcome.tokens_in,
        "tokens_out": outcome.tokens_out,
        "tokens_estimated": outcome.tokens_estimated,
        "cost_micros": outcome.cost_micros,
        "currency": outcome.currency,
        "pricing_unknown": outcome.pricing_unknown,
        "cache_hit": outcome.cache_hit,
        "latency_ms": outcome.latency_ms,
        "model_version": outcome.model_version,
        "call_id": str(outcome.call_id) if outcome.call_id else None,
        "trace_id": str(outcome.trace_id) if outcome.trace_id else None,
        "guardrail_events": outcome.guardrail_events,
        "quota_warnings": outcome.quota_warnings,
    }
