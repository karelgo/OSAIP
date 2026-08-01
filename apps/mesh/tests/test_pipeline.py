"""The pipeline end-to-end: every call lands in the ledger with a span, cache hits are
free but still accounted, and a provider failure is recorded rather than lost."""

import uuid
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from osaip_api.models import LlmCall, LlmCallMessage, Span, Trace
from osaip_mesh.pipeline import CallContext, ConnectionInfo, run_pipeline
from osaip_mesh.providers.base import CompletionRequest, CompletionResult, Message, ProviderError
from osaip_shared.ids import new_id


async def _call(client: httpx.AsyncClient, connection_id: uuid.UUID, **body: Any) -> Any:
    payload = {
        "connection_id": str(connection_id),
        "model": "echo-1",
        "messages": [{"role": "user", "content": "hello there world"}],
        "max_classification": "none",
        **body,
    }
    response = await client.post("/v1/complete", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


async def test_call_is_ledgered_with_messages_and_span(
    mesh_client: httpx.AsyncClient, mesh_session: AsyncSession, make_connection: Any
) -> None:
    connection = await make_connection()
    body = await _call(mesh_client, connection.id)

    call = await mesh_session.get(LlmCall, uuid.UUID(body["call_id"]))
    assert call is not None
    assert call.provider == "echo"
    assert call.model == "echo-1"
    assert call.model_version == "echo-1@echo-1"
    assert call.tokens_in == body["tokens_in"]
    assert call.tokens_out == body["tokens_out"]
    assert call.currency == "EUR"
    assert call.status == "ok"
    assert call.cache_hit is False
    assert call.request_hash is not None and len(call.request_hash) == 64
    assert call.latency_ms >= 0

    # The prompt AND the answer are audited, in order.
    messages = (
        (
            await mesh_session.execute(
                select(LlmCallMessage)
                .where(LlmCallMessage.call_id == call.id)
                .order_by(LlmCallMessage.seq)
            )
        )
        .scalars()
        .all()
    )
    assert [m.role for m in messages] == ["user", "assistant"]
    assert messages[1].content_redacted == body["content"]

    # A span hangs off the trace, and the ledger row points at it.
    assert call.span_id is not None
    span = await mesh_session.get(Span, call.span_id)
    assert span is not None
    assert span.kind == "llm"
    assert span.trace_id == uuid.UUID(body["trace_id"])
    trace = await mesh_session.get(Trace, span.trace_id)
    assert trace is not None and trace.span_count == 1


async def test_caller_supplied_trace_is_reused(
    mesh_client: httpx.AsyncClient, mesh_session: AsyncSession, make_connection: Any
) -> None:
    """Two calls in one build must share the caller's trace, not start two roots."""
    connection = await make_connection()
    trace_id = new_id()
    first = await _call(mesh_client, connection.id, trace_id=str(trace_id))
    second = await _call(
        mesh_client,
        connection.id,
        trace_id=str(trace_id),
        messages=[{"role": "user", "content": "a different prompt"}],
    )
    assert first["trace_id"] == second["trace_id"] == str(trace_id)
    trace = await mesh_session.get(Trace, trace_id)
    assert trace is not None
    assert trace.span_count == 2


async def test_cache_hit_is_free_but_still_ledgered(
    mesh_client: httpx.AsyncClient, mesh_session: AsyncSession, make_connection: Any
) -> None:
    connection = await make_connection(cache_ttl_s=300)
    project_id = str(connection.project_id)

    first = await _call(mesh_client, connection.id, project_id=project_id)
    second = await _call(mesh_client, connection.id, project_id=project_id)

    assert first["cache_hit"] is False
    assert second["cache_hit"] is True
    assert second["content"] == first["content"]
    assert second["cost_micros"] == 0

    # Both calls are in the ledger — a hit must not vanish from usage accounting.
    count = (
        await mesh_session.execute(
            select(func.count()).select_from(LlmCall).where(LlmCall.connection_id == connection.id)
        )
    ).scalar_one()
    assert count == 2
    hit = await mesh_session.get(LlmCall, uuid.UUID(second["call_id"]))
    assert hit is not None and hit.cache_hit is True


async def test_cache_does_not_cross_projects(
    mesh_client: httpx.AsyncClient,
    mesh_session: AsyncSession,
    make_connection: Any,
    make_project: Any,
) -> None:
    """The same prompt through the same connection, from another project, is a miss."""
    connection = await make_connection(cache_ttl_s=300)
    other = await make_project()
    await mesh_session.commit()

    first = await _call(mesh_client, connection.id, project_id=str(connection.project_id))
    second = await _call(mesh_client, connection.id, project_id=str(other.id))
    assert first["cache_hit"] is False
    assert second["cache_hit"] is False


async def test_guardrail_purpose_is_never_cached(
    mesh_client: httpx.AsyncClient, mesh_session: AsyncSession, make_connection: Any
) -> None:
    connection = await make_connection(cache_ttl_s=300)
    await _call(mesh_client, connection.id, purpose="guardrail")
    again = await _call(mesh_client, connection.id, purpose="guardrail")
    assert again["cache_hit"] is False


async def test_caching_is_off_by_default(
    mesh_client: httpx.AsyncClient, mesh_session: AsyncSession, make_connection: Any
) -> None:
    connection = await make_connection()  # cache_ttl_s defaults to 0
    await _call(mesh_client, connection.id)
    again = await _call(mesh_client, connection.id)
    assert again["cache_hit"] is False


class _FailingProvider:
    name = "broken"

    async def complete(self, request: CompletionRequest) -> CompletionResult:
        raise ProviderError("The model provider is rate limiting.", retryable=True)


class _LeakyProvider:
    """Raises something that is NOT a ProviderError, carrying text that must not escape."""

    name = "leaky"

    async def complete(self, request: CompletionRequest) -> CompletionResult:
        raise RuntimeError("connect failed: https://api.example.com?api_key=sk-SECRET")


async def test_provider_failure_is_ledgered_with_status_error(
    mesh_session: AsyncSession, make_project: Any
) -> None:
    project = await make_project()
    await mesh_session.commit()
    connection = ConnectionInfo(id=None, provider="broken")
    request = CompletionRequest(model="m", messages=[Message(role="user", content="hi")])

    with pytest.raises(ProviderError):
        await run_pipeline(
            session=mesh_session,
            make_provider=_FailingProvider,
            connection=connection,
            request=request,
            context=CallContext(project_id=project.id),
        )

    call = (
        await mesh_session.execute(
            select(LlmCall).where(LlmCall.project_id == project.id, LlmCall.status == "error")
        )
    ).scalar_one()
    assert call.tokens_in == 0
    assert call.cost_micros == 0
    span = await mesh_session.get(Span, call.span_id)
    assert span is not None and span.status == "error"


async def test_unexpected_provider_exception_is_sanitized(mesh_session: AsyncSession) -> None:
    """A raw driver/HTTP message could carry the API key — it must never surface."""
    request = CompletionRequest(model="m", messages=[Message(role="user", content="hi")])
    with pytest.raises(ProviderError) as excinfo:
        await run_pipeline(
            session=mesh_session,
            make_provider=_LeakyProvider,
            connection=ConnectionInfo(id=None, provider="leaky"),
            request=request,
            context=CallContext(),
        )
    assert "sk-SECRET" not in excinfo.value.public_message
    assert "api.example.com" not in excinfo.value.public_message
