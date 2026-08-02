"""Guardrails through the real pipeline.

Two Phase-3a acceptance clauses live here:
  · a prompt containing a BSN is stored redacted and the raw never persists;
  · a `bsn`-labelled payload to an `external` connection is hard-blocked with an audit
    event.
"""

import uuid
from typing import Any

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from osaip_api.models import AuditLog, GuardrailEvent, GuardrailPolicy, LlmCall, LlmCallMessage
from osaip_shared.ids import new_id

BSN = "111222333"


async def _post(client: httpx.AsyncClient, connection_id: uuid.UUID, **body: Any) -> httpx.Response:
    payload = {
        "connection_id": str(connection_id),
        "model": "echo-1",
        "messages": [{"role": "user", "content": f"De klant met BSN {BSN} belde."}],
        **body,
    }
    return await client.post("/v1/complete", json=payload)


# ── AC-4: redaction ──────────────────────────────────────────────────────────────


async def test_a_bsn_is_redacted_before_the_provider_and_in_the_audit(
    mesh_client: httpx.AsyncClient, mesh_session: AsyncSession, make_connection: Any
) -> None:
    connection = await make_connection()
    response = await _post(mesh_client, connection.id, max_classification="bsn")
    assert response.status_code == 200, response.text
    body = response.json()

    # The echo provider echoes what it was SENT, so the answer proves the provider
    # never saw the BSN — redaction happens before the call, not just before storage.
    assert BSN not in body["content"]
    assert "<BSN>" in body["content"]

    rows = (
        (
            await mesh_session.execute(
                select(LlmCallMessage).where(LlmCallMessage.call_id == uuid.UUID(body["call_id"]))
            )
        )
        .scalars()
        .all()
    )
    assert rows
    for row in rows:
        assert BSN not in row.content_redacted
        assert row.content_raw is None  # audit_mode='redacted': no raw copy at all


async def test_full_audit_mode_keeps_the_raw_prompt(
    mesh_client: httpx.AsyncClient, mesh_session: AsyncSession, make_connection: Any
) -> None:
    """`full` is the sanctioned way to retain raw text — and it still redacts before the
    provider call, it only adds a second stored copy."""
    connection = await make_connection(audit_mode="full")
    body = (await _post(mesh_client, connection.id, max_classification="bsn")).json()

    assert BSN not in body["content"]  # the provider still never saw it
    rows = (
        (
            await mesh_session.execute(
                select(LlmCallMessage)
                .where(LlmCallMessage.call_id == uuid.UUID(body["call_id"]))
                .order_by(LlmCallMessage.seq)
            )
        )
        .scalars()
        .all()
    )
    assert rows[0].content_raw is not None and BSN in rows[0].content_raw


async def test_redaction_is_recorded_as_a_guardrail_event(
    mesh_client: httpx.AsyncClient, mesh_session: AsyncSession, make_connection: Any
) -> None:
    connection = await make_connection()
    body = (await _post(mesh_client, connection.id, max_classification="bsn")).json()

    events = (
        (
            await mesh_session.execute(
                select(GuardrailEvent).where(GuardrailEvent.call_id == uuid.UUID(body["call_id"]))
            )
        )
        .scalars()
        .all()
    )
    rules = {e.rule for e in events}
    assert "pii.regex" in rules
    assert "cp11.residency" in rules  # allowed calls are evented too
    for event in events:
        assert BSN not in str(event.details)  # counts, never values


async def test_the_response_is_returned_to_the_caller_verbatim(
    mesh_client: httpx.AsyncClient, make_connection: Any
) -> None:
    """`post` redaction protects the stored copy; the caller still gets the answer."""
    connection = await make_connection()
    response = await mesh_client.post(
        "/v1/complete",
        json={
            "connection_id": str(connection.id),
            "model": "echo-1",
            "messages": [{"role": "user", "content": "geen persoonsgegevens hier"}],
            "max_classification": "none",
        },
    )
    assert "geen persoonsgegevens hier" in response.json()["content"]


# ── AC-5: CP-11 ──────────────────────────────────────────────────────────────────


async def test_bsn_to_an_external_connection_is_blocked_and_audited(
    mesh_client: httpx.AsyncClient, mesh_session: AsyncSession, make_connection: Any
) -> None:
    # A non-echo provider, because echo is refused at non-local residency for its own
    # reasons and we want the CP-11 gate to be what bites.
    connection = await make_connection(
        provider="openai", allowed_models=["gpt-4o"], data_residency="external"
    )
    before = (await mesh_session.execute(select(func.count()).select_from(AuditLog))).scalar_one()

    response = await mesh_client.post(
        "/v1/complete",
        json={
            "connection_id": str(connection.id),
            "model": "gpt-4o",
            "messages": [{"role": "user", "content": f"BSN {BSN}"}],
            "max_classification": "bsn",
        },
    )
    assert response.status_code == 403
    problem = response.json()
    assert problem["type"] == "urn:osaip:problem:residency-blocked"
    assert problem["classification"] == "bsn"
    assert problem["data_residency"] == "external"
    assert "local" in problem["detail"]  # says what to change

    # The refusal is in the chained audit and in guardrail_events, even though no call
    # row will ever exist for it.
    after = (await mesh_session.execute(select(func.count()).select_from(AuditLog))).scalar_one()
    assert after == before + 1
    entry = (
        await mesh_session.execute(
            select(AuditLog)
            .where(AuditLog.action == "llm.residency_blocked")
            .order_by(AuditLog.seq.desc())
            .limit(1)
        )
    ).scalar_one()
    assert entry.details["residency_is_operator_asserted"] is True

    blocked = (
        (
            await mesh_session.execute(
                select(GuardrailEvent).where(
                    GuardrailEvent.rule == "cp11.residency", GuardrailEvent.action == "block"
                )
            )
        )
        .scalars()
        .all()
    )
    assert blocked


async def test_an_undeclared_classification_is_blocked_on_an_external_connection(
    mesh_client: httpx.AsyncClient, make_connection: Any
) -> None:
    """Fail-closed: omitting the declaration must not buy the most permissive routing."""
    connection = await make_connection(
        provider="openai", allowed_models=["gpt-4o"], data_residency="external"
    )
    response = await mesh_client.post(
        "/v1/complete",
        json={
            "connection_id": str(connection.id),
            "model": "gpt-4o",
            "messages": [{"role": "user", "content": "hallo"}],
        },
    )
    assert response.status_code == 403


async def test_non_personal_data_may_go_external(
    mesh_client: httpx.AsyncClient, make_connection: Any
) -> None:
    """The gate must not block everything — `none` routes anywhere.

    It gets past CP-11 and into the provider, where this keyless test connection fails
    for its own reasons. The point is that the answer is not 403."""
    connection = await make_connection(
        provider="openai", allowed_models=["gpt-4o"], data_residency="external"
    )
    response = await mesh_client.post(
        "/v1/complete",
        json={
            "connection_id": str(connection.id),
            "model": "gpt-4o",
            "messages": [{"role": "user", "content": "wat is 2+2"}],
            "max_classification": "none",
        },
    )
    assert response.status_code != 403  # not blocked by CP-11
    assert response.status_code == 502  # reached the provider adapter


async def test_a_blocked_call_never_reaches_the_ledger(
    mesh_client: httpx.AsyncClient, mesh_session: AsyncSession, make_connection: Any
) -> None:
    connection = await make_connection(
        provider="openai", allowed_models=["gpt-4o"], data_residency="external"
    )
    await mesh_client.post(
        "/v1/complete",
        json={
            "connection_id": str(connection.id),
            "model": "gpt-4o",
            "messages": [{"role": "user", "content": f"BSN {BSN}"}],
            "max_classification": "bsn",
        },
    )
    count = (
        await mesh_session.execute(
            select(func.count()).select_from(LlmCall).where(LlmCall.connection_id == connection.id)
        )
    ).scalar_one()
    assert count == 0


# ── policy ───────────────────────────────────────────────────────────────────────


async def test_a_policy_can_add_a_length_limit(
    mesh_client: httpx.AsyncClient, mesh_session: AsyncSession, make_connection: Any
) -> None:
    policy = GuardrailPolicy(
        id=new_id(),
        project_id=None,
        name=f"short-{uuid.uuid4().hex[:6]}",
        stages={"pre": {"max_input_chars": 10}},
    )
    mesh_session.add(policy)
    await mesh_session.commit()
    connection = await make_connection(guardrail_policy_id=policy.id)

    response = await mesh_client.post(
        "/v1/complete",
        json={
            "connection_id": str(connection.id),
            "model": "echo-1",
            "messages": [{"role": "user", "content": "far more than ten characters"}],
            "max_classification": "none",
        },
    )
    assert response.status_code == 422
    assert response.json()["type"] == "urn:osaip:problem:guardrail-input"


async def test_a_policy_cannot_switch_redaction_off(
    mesh_client: httpx.AsyncClient, mesh_session: AsyncSession, make_connection: Any
) -> None:
    """BIO2 8.12: the baseline is not configurable away. A policy that tries is ignored."""
    policy = GuardrailPolicy(
        id=new_id(),
        project_id=None,
        name=f"nopii-{uuid.uuid4().hex[:6]}",
        stages={"pre": {"redact_pii": False, "pii": "off", "disable_baseline": True}},
    )
    mesh_session.add(policy)
    await mesh_session.commit()
    connection = await make_connection(guardrail_policy_id=policy.id)

    body = (await _post(mesh_client, connection.id, max_classification="bsn")).json()
    assert BSN not in body["content"]
    assert "<BSN>" in body["content"]


async def test_a_policy_can_require_an_output_shape(
    mesh_client: httpx.AsyncClient, mesh_session: AsyncSession, make_connection: Any
) -> None:
    """Echo never returns JSON, so a schema policy must reject its answer rather than
    pass malformed data downstream."""
    policy = GuardrailPolicy(
        id=new_id(),
        project_id=None,
        name=f"shape-{uuid.uuid4().hex[:6]}",
        stages={"post": {"schema": {"type": "object", "required": ["label"]}}},
    )
    mesh_session.add(policy)
    await mesh_session.commit()
    connection = await make_connection(guardrail_policy_id=policy.id)

    response = await mesh_client.post(
        "/v1/complete",
        json={
            "connection_id": str(connection.id),
            "model": "echo-1",
            "messages": [{"role": "user", "content": "classify this"}],
            "max_classification": "none",
        },
    )
    assert response.status_code == 422
    assert response.json()["type"] == "urn:osaip:problem:guardrail-output"
