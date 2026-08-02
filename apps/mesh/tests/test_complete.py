"""`POST /v1/complete`: service-token auth, model allowlist, echo determinism, and
the echo-must-be-local rule (a mock may never stand in for a real provider)."""

import uuid
from typing import Any

import httpx
import pytest

# `make_connection` is a conftest fixture (an async builder); tests annotate it Any
# rather than importing across test modules — the tests dir is not a package.


async def test_requires_service_token(mesh_app: Any, make_connection: Any) -> None:
    connection = await make_connection()
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
    mesh_client: httpx.AsyncClient, make_connection: Any
) -> None:
    connection = await make_connection()
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
    mesh_client: httpx.AsyncClient, make_connection: Any
) -> None:
    connection = await make_connection(allowed_models=["echo-1"])
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
    mesh_client: httpx.AsyncClient, make_connection: Any
) -> None:
    """A mock must never be configured as if it were an external provider."""
    connection = await make_connection(data_residency="external")
    response = await mesh_client.post(
        "/v1/complete",
        json={
            "connection_id": str(connection.id),
            "model": "echo-1",
            "messages": [{"role": "user", "content": "hi"}],
            # Declared `none` so the CP-11 gate lets it through and the echo-must-be-
            # local rule is what bites.
            "max_classification": "none",
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


@pytest.mark.parametrize("provider", ["openai", "anthropic"])
async def test_hosted_providers_route_to_the_litellm_adapter(
    mesh_client: httpx.AsyncClient, make_connection: Any, provider: str
) -> None:
    """Since slice 5 these are wired. A keyless hosted connection is refused as a
    configuration problem (502 provider-failed), NOT as a retryable outage — the
    distinction is what stops a caller retrying forever."""
    connection = await make_connection(
        provider=provider, allowed_models=[], data_residency="external"
    )
    response = await mesh_client.post(
        "/v1/complete",
        json={
            "connection_id": str(connection.id),
            "model": "some-model",
            "messages": [{"role": "user", "content": "hi"}],
            "max_classification": "none",  # past the CP-11 gate, into the provider
        },
    )
    assert response.status_code == 502
    body = response.json()
    assert body["type"] == "urn:osaip:problem:provider-failed"
    assert "no API key" in body["detail"]
