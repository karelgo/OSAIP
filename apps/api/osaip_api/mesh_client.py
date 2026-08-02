"""The API's client for the internal mesh service.

The API never calls a model provider itself (§5b) — it calls the mesh, which owns the
residency gate, the guardrails, the budgets and the ledger. This module exists so that
rule has exactly one implementation and the service token lives in exactly one place.

It deliberately does NOT import anything from `osaip_mesh`: the mesh is a separate
service reachable over HTTP, and importing its code here would quietly turn a service
boundary into a shared library that only looks like a boundary.
"""

import uuid
from dataclasses import dataclass
from typing import Any

import httpx

# A connection test is interactive — someone is watching a spinner — so it fails fast
# rather than hanging on an unreachable provider.
TEST_TIMEOUT_S = 30.0


@dataclass
class MeshCallFailed(Exception):
    """The mesh refused or could not complete the call. Carries the problem+json the
    mesh produced, which is already sanitised for display."""

    status: int
    detail: str
    hint: str | None = None
    slug: str | None = None

    def __str__(self) -> str:
        return self.detail


async def call_mesh(
    settings: Any,
    *,
    connection_id: uuid.UUID,
    model: str,
    messages: list[dict[str, str]],
    project_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    purpose: str = "general",
    max_classification: str = "bijzonder",
    max_tokens: int = 512,
    timeout_s: float = TEST_TIMEOUT_S,
) -> dict[str, Any]:
    """POST /v1/complete on the mesh. Raises MeshCallFailed on any non-2xx."""
    payload: dict[str, Any] = {
        "connection_id": str(connection_id),
        "model": model,
        "messages": messages,
        "purpose": purpose,
        # Callers MUST declare; the default here matches the mesh's own fail-closed
        # default so a forgotten argument cannot widen routing.
        "max_classification": max_classification,
        "max_tokens": max_tokens,
    }
    if project_id:
        payload["project_id"] = str(project_id)
    if user_id:
        payload["user_id"] = str(user_id)

    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            response = await client.post(
                f"{settings.mesh_url.rstrip('/')}/v1/complete",
                json=payload,
                headers={"X-OSAIP-Mesh-Token": settings.mesh_service_token},
            )
    except httpx.HTTPError as exc:
        # The mesh being unreachable is an operational fault, not a user error, and its
        # transport text can name internal hosts — so it is reported, not forwarded.
        raise MeshCallFailed(
            status=503,
            detail="The LLM mesh is unreachable.",
            hint="Check that the mesh service is running and OSAIP_MESH_URL is correct.",
            slug="mesh-unreachable",
        ) from exc

    if response.status_code >= 400:
        body = _problem(response)
        raise MeshCallFailed(
            status=response.status_code,
            detail=str(body.get("detail") or "The model call failed."),
            hint=body.get("hint"),
            slug=str(body.get("type", "")).rsplit(":", 1)[-1] or None,
        )
    result: dict[str, Any] = response.json()
    return result


def _problem(response: httpx.Response) -> dict[str, Any]:
    try:
        parsed = response.json()
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}
