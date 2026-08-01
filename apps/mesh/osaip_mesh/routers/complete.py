"""`POST /v1/complete` — the one entry point for a model call.

`/v1/stream` is deliberately absent in 3a: nothing consumes streams yet, and streaming
needs a post-guardrail design (you cannot unsend tokens) that belongs with the first
streaming consumer — recorded in docs/plans/phase-3a.md.
"""

import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from osaip_api.db import get_session
from osaip_api.models import LlmConnection, Secret
from osaip_api.problem import Problem
from osaip_mesh.pipeline import CallContext, MeshOutcome, messages_from_payload, run_pipeline
from osaip_mesh.providers.base import CompletionRequest, ProviderError
from osaip_mesh.providers.echo import EchoProvider

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
    # litellm-backed providers land in slice 5.
    raise Problem(
        501,
        title="Provider not available yet",
        detail=f"The {connection.provider!r} provider arrives with the LiteLLM adapter.",
        hint="Use an echo connection until then.",
        slug="not-implemented",
    )


@router.post("/complete", response_model=CompleteOut)
async def complete(body: CompleteIn, request: Request, session: DbSession) -> dict[str, Any]:
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
    provider = _build_provider(connection, secret)

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
    try:
        outcome: MeshOutcome = await run_pipeline(
            provider=provider,
            provider_name=connection.provider,
            request=completion,
            context=context,
        )
    except ProviderError as exc:
        raise Problem(
            502,
            title="Model call failed",
            detail=exc.public_message,  # sanitized by the adapter — never raw HTTP text
            hint="Check the connection settings, or retry if the provider is rate-limiting.",
            slug="provider-rate-limited" if exc.retryable else "provider-failed",
        ) from exc

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
    }
