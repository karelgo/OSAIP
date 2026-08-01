"""`POST /v1/complete`: service-token auth, model allowlist, echo determinism, and
the echo-must-be-local rule (a mock may never stand in for a real provider)."""

import uuid
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from osaip_api.models import LlmConnection, Project
from osaip_shared.ids import new_id


async def _project(session: AsyncSession) -> Project:
    project = Project(id=new_id(), key=f"m{uuid.uuid4().hex[:8]}", name="mesh", storage_prefix="p")
    session.add(project)
    await session.flush()
    return project


async def _connection(session: AsyncSession, **overrides: Any) -> LlmConnection:
    project = await _project(session)
    connection = LlmConnection(
        id=new_id(),
        scope="project",
        project_id=project.id,
        name=overrides.pop("name", f"echo-{uuid.uuid4().hex[:6]}"),
        provider=overrides.pop("provider", "echo"),
        base_config=overrides.pop("base_config", {}),
        allowed_models=overrides.pop("allowed_models", ["echo-1"]),
        data_residency=overrides.pop("data_residency", "local"),
        legal_basis="demo",
        purpose_codes=["demo"],
        **overrides,
    )
    session.add(connection)
    await session.commit()
    return connection


async def test_requires_service_token(mesh_app: Any, mesh_session: AsyncSession) -> None:
    connection = await _connection(mesh_session)
    transport = httpx.ASGITransport(app=mesh_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://mesh") as anon:
        response = await anon.post(
            "/v1/complete",
            json={
                "connection_id": str(connection.id),
                "model": "echo-1",
                "messages": [{"role": "user", "content": "hi"}],
            },
        )
    assert response.status_code == 401
    assert response.json()["type"] == "urn:osaip:problem:unauthenticated"


async def test_echo_completion_is_deterministic_and_counted(
    mesh_client: httpx.AsyncClient, mesh_session: AsyncSession
) -> None:
    connection = await _connection(mesh_session)
    payload = {
        "connection_id": str(connection.id),
        "model": "echo-1",
        "messages": [{"role": "user", "content": "hello there world"}],
        "max_classification": "none",
    }
    first = await mesh_client.post("/v1/complete", json=payload)
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["tokens_in"] == 3
    assert body["tokens_out"] > 0
    assert body["currency"] == "EUR"
    assert body["pricing_unknown"] is False  # echo is free but priced
    assert body["cost_micros"] == 0
    assert body["model_version"] == "echo-1@echo-1"

    second = await mesh_client.post("/v1/complete", json=payload)
    assert second.json()["content"] == body["content"]  # deterministic


async def test_model_allowlist_is_enforced(
    mesh_client: httpx.AsyncClient, mesh_session: AsyncSession
) -> None:
    connection = await _connection(mesh_session, allowed_models=["echo-1"])
    response = await mesh_client.post(
        "/v1/complete",
        json={
            "connection_id": str(connection.id),
            "model": "gpt-4o",
            "messages": [{"role": "user", "content": "hi"}],
        },
    )
    assert response.status_code == 422
    assert response.json()["type"] == "urn:osaip:problem:model-not-allowed"


async def test_echo_refuses_non_local_residency(
    mesh_client: httpx.AsyncClient, mesh_session: AsyncSession
) -> None:
    """A mock must never be configured as if it were an external provider."""
    connection = await _connection(mesh_session, data_residency="external")
    response = await mesh_client.post(
        "/v1/complete",
        json={
            "connection_id": str(connection.id),
            "model": "echo-1",
            "messages": [{"role": "user", "content": "hi"}],
        },
    )
    assert response.status_code == 422
    assert "local" in response.json()["detail"]


async def test_unknown_connection_404(mesh_client: httpx.AsyncClient) -> None:
    response = await mesh_client.post(
        "/v1/complete",
        json={
            "connection_id": str(uuid.uuid4()),
            "model": "echo-1",
            "messages": [{"role": "user", "content": "hi"}],
        },
    )
    assert response.status_code == 404


@pytest.mark.parametrize("provider", ["openai", "anthropic", "ollama"])
async def test_litellm_providers_are_not_wired_yet(
    mesh_client: httpx.AsyncClient, mesh_session: AsyncSession, provider: str
) -> None:
    connection = await _connection(
        mesh_session, provider=provider, allowed_models=[], data_residency="external"
    )
    response = await mesh_client.post(
        "/v1/complete",
        json={
            "connection_id": str(connection.id),
            "model": "some-model",
            "messages": [{"role": "user", "content": "hi"}],
        },
    )
    assert response.status_code == 501  # arrives with the LiteLLM adapter (slice 5)
