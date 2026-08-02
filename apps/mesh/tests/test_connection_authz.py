"""Connection authz at the choke point, and the per-request output schema (ADR-0010 §4-5).

3b is the first phase where a user-editable config field carries an arbitrary connection
UUID into the mesh. Before this, the only scope check lived in API routes that the
worker's build path and Prompt Studio will never traverse.
"""

from typing import Any

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from osaip_api.models import LlmCall
from osaip_guardrails.policy import merge_policy

PERSON = {"type": "object", "required": ["label"]}


async def _post(client: httpx.AsyncClient, **body: Any) -> httpx.Response:
    payload = {
        "model": "echo-1",
        "messages": [{"role": "user", "content": "hallo"}],
        "max_classification": "none",
        **body,
    }
    return await client.post("/v1/complete", json=payload)


# ── authz ───────────────────────────────────────────────────────────────────────


async def test_another_projects_connection_is_refused(
    mesh_client: httpx.AsyncClient,
    mesh_session: AsyncSession,
    make_connection: Any,
    make_project: Any,
) -> None:
    """The whole point: learning another project's connection id must not hand over its
    API key, its model allowlist and its budget."""
    connection = await make_connection()  # owned by its own project
    intruder = await make_project()
    await mesh_session.commit()

    response = await _post(
        mesh_client, connection_id=str(connection.id), project_id=str(intruder.id)
    )
    # 404, not 403 — a 403 would confirm the id exists somewhere.
    assert response.status_code == 404
    assert response.json()["type"] == "urn:osaip:problem:not-found"

    # Refused before anything was spent or recorded.
    count = (
        await mesh_session.execute(
            select(func.count()).select_from(LlmCall).where(LlmCall.connection_id == connection.id)
        )
    ).scalar_one()
    assert count == 0


async def test_the_owning_project_may_use_it(
    mesh_client: httpx.AsyncClient, make_connection: Any
) -> None:
    connection = await make_connection()
    response = await _post(
        mesh_client, connection_id=str(connection.id), project_id=str(connection.project_id)
    )
    assert response.status_code == 200, response.text


async def test_a_global_connection_is_usable_from_any_project(
    mesh_client: httpx.AsyncClient,
    mesh_session: AsyncSession,
    make_connection: Any,
    make_project: Any,
) -> None:
    """Global connections exist precisely so every project can use them."""
    connection = await make_connection()
    connection.scope = "global"
    connection.project_id = None
    await mesh_session.commit()
    other = await make_project()
    await mesh_session.commit()

    response = await _post(mesh_client, connection_id=str(connection.id), project_id=str(other.id))
    assert response.status_code == 200, response.text


async def test_a_project_scoped_connection_needs_a_declared_project(
    mesh_client: httpx.AsyncClient, make_connection: Any
) -> None:
    """A caller that declares no project cannot satisfy the owner check, and must not be
    let through by omission."""
    connection = await make_connection()
    response = await _post(mesh_client, connection_id=str(connection.id))
    assert response.status_code == 404


async def test_authz_runs_before_the_residency_gate(
    mesh_client: httpx.AsyncClient,
    mesh_session: AsyncSession,
    make_connection: Any,
    make_project: Any,
) -> None:
    """§5b's order: authz first. A cross-project attempt must not be reported as a
    sovereignty problem, which would tell the caller the connection exists."""
    connection = await make_connection(
        provider="openai", allowed_models=["gpt-4o"], data_residency="external"
    )
    intruder = await make_project()
    await mesh_session.commit()

    response = await _post(
        mesh_client,
        connection_id=str(connection.id),
        model="gpt-4o",
        project_id=str(intruder.id),
        max_classification="bsn",  # would be a 403 residency block if authz ran second
    )
    assert response.status_code == 404


# ── per-request output schema ───────────────────────────────────────────────────


def test_a_request_schema_applies_when_the_policy_pins_none() -> None:
    policy = merge_policy(None, PERSON)
    assert policy.output_schema == PERSON


def test_a_policy_schema_wins_over_the_request() -> None:
    """A caller must not be able to LOOSEN a shape an operator set — the same
    add-never-remove rule as the PII baseline."""
    operator = {"type": "object", "required": ["label", "confidence"]}
    policy = merge_policy({"post": {"schema": operator}}, {"type": "object"})
    assert policy.output_schema == operator


def test_no_schema_anywhere_stays_none() -> None:
    assert merge_policy(None, None).output_schema is None


async def test_a_request_schema_is_enforced_end_to_end(
    mesh_client: httpx.AsyncClient, make_connection: Any
) -> None:
    """Echo never returns JSON, so a request-supplied schema must reject its answer —
    proving the schema reached the post stage rather than being ignored."""
    connection = await make_connection()
    response = await _post(
        mesh_client,
        connection_id=str(connection.id),
        project_id=str(connection.project_id),
        output_schema=PERSON,
    )
    assert response.status_code == 422
    assert response.json()["type"] == "urn:osaip:problem:guardrail-output"


async def test_without_a_schema_the_same_call_succeeds(
    mesh_client: httpx.AsyncClient, make_connection: Any
) -> None:
    """Guards the test above against passing for the wrong reason."""
    connection = await make_connection()
    response = await _post(
        mesh_client, connection_id=str(connection.id), project_id=str(connection.project_id)
    )
    assert response.status_code == 200, response.text
