"""LLM connections, quotas, usage, prompts and policies over HTTP.

The load-bearing assertions are the ones about what the API REFUSES: a secret it will
never read back, a residency declaration that contradicts the provider, a budget with
no limit, and a prompt template that hand-rolls the §5d delimiters.
"""

import datetime
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from osaip_api.models import AuditLog, LlmCall, LlmConnection, Project, Quota, Secret
from osaip_shared.ids import new_id

LoginAs = Callable[..., Awaitable[httpx.AsyncClient]]

CONNECTION: dict[str, Any] = {
    "name": "echo-dev",
    "provider": "echo",
    "allowed_models": ["echo-1"],
    "data_residency": "local",
    "legal_basis": "Art 6(1)(e) AVG — public task",
    "purpose_codes": ["analytics.internal"],
}


async def _project(client: httpx.AsyncClient, key: str) -> None:
    """Projects are addressed by KEY throughout the API; it never hands out the uuid."""
    response = await client.post("/api/v1/projects", json={"key": key, "name": key})
    assert response.status_code == 201, response.text


async def _project_id(session: AsyncSession, key: str) -> uuid.UUID:
    project_id = (await session.execute(select(Project.id).where(Project.key == key))).scalar_one()
    return project_id


async def _create(client: httpx.AsyncClient, key: str, **overrides: Any) -> httpx.Response:
    return await client.post(
        f"/api/v1/projects/{key}/llm-connections", json={**CONNECTION, **overrides}
    )


# ── connections ─────────────────────────────────────────────────────────────────


async def test_create_and_read_back(login_as: LoginAs) -> None:
    admin = await login_as("sub-llm-1", "llm1@osaip.dev")
    await _project(admin, "llmp1")

    created = await _create(admin, "llmp1")
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["provider"] == "echo"
    assert body["has_secret"] is False
    # Stated on every read so nothing downstream can present the declaration as if the
    # platform had verified the geography (ADR-0008 §7).
    assert body["residency_is_operator_asserted"] is True

    listed = await admin.get("/api/v1/projects/llmp1/llm-connections")
    assert listed.status_code == 200
    assert [c["name"] for c in listed.json()["items"]] == ["echo-dev"]
    assert listed.headers.get("ETag")


async def test_a_secret_is_write_only(login_as: LoginAs, db_session: AsyncSession) -> None:
    """Not even the admin who set it can read it back through the API."""
    admin = await login_as("sub-llm-2", "llm2@osaip.dev")
    await _project(admin, "llmp2")

    created = await _create(
        admin,
        "llmp2",
        name="openai-prod",
        provider="openai",
        data_residency="external",
        allowed_models=["gpt-4o-mini"],
        secret="sk-Probe-Secret-9000x",
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["has_secret"] is True
    assert "sk-Probe-Secret-9000x" not in created.text

    detail = await admin.get(f"/api/v1/projects/llmp2/llm-connections/{body['id']}")
    assert "sk-Probe-Secret-9000x" not in detail.text
    assert "secret" not in detail.json()

    # It IS stored — encrypted. The ciphertext must not contain the plaintext.
    connection = await db_session.get(LlmConnection, uuid.UUID(body["id"]))
    assert connection is not None and connection.secret_id is not None
    secret = await db_session.get(Secret, connection.secret_id)
    assert secret is not None
    assert "sk-Probe-Secret-9000x" not in str(secret.ciphertext)


@pytest.mark.parametrize(
    ("provider", "residency"),
    [("openai", "local"), ("openai", "eu"), ("anthropic", "local"), ("echo", "external")],
)
async def test_residency_must_match_the_provider(
    login_as: LoginAs, provider: str, residency: str
) -> None:
    """Declaring a hosted vendor `local` is the most consequential mistake available
    here — it would silently defeat the CP-11 gate at the mesh."""
    admin = await login_as(f"sub-llm-r-{provider}-{residency}", f"r{provider}{residency}@o.dev")
    key = f"llmr{provider}{residency}"[:20]
    await _project(admin, key)
    response = await _create(
        admin, key, name=f"{provider}-x", provider=provider, data_residency=residency
    )
    assert response.status_code == 422
    assert response.json()["type"] == "urn:osaip:problem:validation"


async def test_compliance_fields_are_mandatory(login_as: LoginAs) -> None:
    """CP-2: a connection is a processor, and a RoPA needs to say why."""
    admin = await login_as("sub-llm-3", "llm3@osaip.dev")
    await _project(admin, "llmp3")
    payload = {k: v for k, v in CONNECTION.items() if k not in {"legal_basis", "purpose_codes"}}
    response = await admin.post("/api/v1/projects/llmp3/llm-connections", json=payload)
    assert response.status_code == 422


async def test_editors_and_viewers_cannot_manage_connections(login_as: LoginAs) -> None:
    admin = await login_as("sub-llm-4", "llm4@osaip.dev")
    await _project(admin, "llmp4")
    # They must exist as users before a role can be granted, so they sign in first.
    editor = await login_as("sub-llm-editor", "llm-editor@osaip.dev")
    viewer = await login_as("sub-llm-viewer", "llm-viewer@osaip.dev")
    granted = await admin.put(
        "/api/v1/projects/llmp4/members",
        json={
            "members": [
                # The PUT replaces the whole list, so the admin has to stay in it.
                {"email": "llm4@osaip.dev", "role": "admin"},
                {"email": "llm-editor@osaip.dev", "role": "editor"},
                {"email": "llm-viewer@osaip.dev", "role": "viewer"},
            ]
        },
    )
    assert granted.status_code == 200, granted.text
    assert (await _create(editor, "llmp4", name="e")).status_code == 403
    assert (await _create(viewer, "llmp4", name="v")).status_code == 403
    # A viewer may still SEE them — the models a project can use are not a secret.
    assert (await viewer.get("/api/v1/projects/llmp4/llm-connections")).status_code == 200


async def test_a_name_collision_is_a_conflict(login_as: LoginAs) -> None:
    admin = await login_as("sub-llm-5", "llm5@osaip.dev")
    await _project(admin, "llmp5")
    assert (await _create(admin, "llmp5")).status_code == 201
    assert (await _create(admin, "llmp5")).status_code == 409


async def test_another_projects_connection_is_not_found(login_as: LoginAs) -> None:
    """Whether another project owns this id is not this project's business."""
    admin = await login_as("sub-llm-6", "llm6@osaip.dev")
    await _project(admin, "llmp6a")
    await _project(admin, "llmp6b")
    created = await _create(admin, "llmp6a")
    response = await admin.get(f"/api/v1/projects/llmp6b/llm-connections/{created.json()['id']}")
    assert response.status_code == 404


async def test_changing_the_audit_mode_is_audited_on_its_own_terms(
    login_as: LoginAs, db_session: AsyncSession
) -> None:
    """audit_mode decides whether raw prompt text is retained, so the change must be
    findable without reading a field list."""
    admin = await login_as("sub-llm-7", "llm7@osaip.dev")
    await _project(admin, "llmp7")
    created = await _create(admin, "llmp7")

    patched = await admin.patch(
        f"/api/v1/projects/llmp7/llm-connections/{created.json()['id']}",
        json={"audit_mode": "full"},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["audit_mode"] == "full"

    entry = (
        await db_session.execute(
            select(AuditLog).where(
                AuditLog.action == "llm_connection.audit_mode_changed",
                AuditLog.object_id == created.json()["id"],
            )
        )
    ).scalar_one()
    assert entry.details["to"] == "full"


async def test_archiving_keeps_the_row(login_as: LoginAs, db_session: AsyncSession) -> None:
    """The ledger references connections; deleting one would orphan the history of what
    was sent where."""
    admin = await login_as("sub-llm-8", "llm8@osaip.dev")
    await _project(admin, "llmp8")
    created = await _create(admin, "llmp8")
    connection_id = uuid.UUID(created.json()["id"])

    assert (
        await admin.delete(f"/api/v1/projects/llmp8/llm-connections/{connection_id}")
    ).status_code == 204

    row = await db_session.get(LlmConnection, connection_id)
    assert row is not None and row.status == "archived"
    assert (await admin.get("/api/v1/projects/llmp8/llm-connections")).json()["items"] == []


async def test_test_endpoint_degrades_to_a_readable_verdict(login_as: LoginAs) -> None:
    """No mesh runs in these tests, so this exercises the unreachable path: it must
    report a verdict rather than 500, and must not leak transport detail."""
    admin = await login_as("sub-llm-9", "llm9@osaip.dev")
    await _project(admin, "llmp9")
    created = await _create(admin, "llmp9")

    response = await admin.post(
        f"/api/v1/projects/llmp9/llm-connections/{created.json()['id']}/test"
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["detail"]
    assert "Traceback" not in response.text


# ── quotas ──────────────────────────────────────────────────────────────────────


async def test_quota_crud(login_as: LoginAs, db_session: AsyncSession) -> None:
    admin = await login_as("sub-q-1", "q1@osaip.dev")
    await _project(admin, "llmq1")

    created = await admin.post(
        "/api/v1/projects/llmq1/quotas",
        json={"period": "month", "limit_cost_micros": 5_000_000, "action": "block"},
    )
    assert created.status_code == 201, created.text
    quota_id = created.json()["id"]

    assert len((await admin.get("/api/v1/projects/llmq1/quotas")).json()["items"]) == 1

    patched = await admin.patch(
        f"/api/v1/projects/llmq1/quotas/{quota_id}", json={"action": "warn"}
    )
    assert patched.json()["action"] == "warn"

    assert (await admin.delete(f"/api/v1/projects/llmq1/quotas/{quota_id}")).status_code == 204
    assert await db_session.get(Quota, uuid.UUID(quota_id)) is None


async def test_a_quota_needs_at_least_one_limit(login_as: LoginAs) -> None:
    """A limitless quota is not permissive — it is a no-op that looks like a control."""
    admin = await login_as("sub-q-2", "q2@osaip.dev")
    await _project(admin, "llmq2")
    response = await admin.post("/api/v1/projects/llmq2/quotas", json={"period": "month"})
    assert response.status_code == 422


async def test_a_project_admin_cannot_budget_another_project(
    login_as: LoginAs, db_session: AsyncSession
) -> None:
    admin = await login_as("sub-q-3", "q3@osaip.dev")
    await _project(admin, "llmq3a")
    await _project(admin, "llmq3b")
    other_id = str(await _project_id(db_session, "llmq3b"))
    response = await admin.post(
        "/api/v1/projects/llmq3a/quotas",
        json={
            "scope_type": "project",
            "scope_id": other_id,
            "period": "month",
            "limit_calls": 10,
        },
    )
    assert response.status_code == 403


async def test_a_duplicate_period_is_a_conflict(login_as: LoginAs) -> None:
    admin = await login_as("sub-q-4", "q4@osaip.dev")
    await _project(admin, "llmq4")
    body: dict[str, Any] = {"period": "day", "limit_calls": 5}
    assert (await admin.post("/api/v1/projects/llmq4/quotas", json=body)).status_code == 201
    assert (await admin.post("/api/v1/projects/llmq4/quotas", json=body)).status_code == 409
    # A DIFFERENT period on the same scope is legitimate — both budgets bite.
    body["period"] = "month"
    assert (await admin.post("/api/v1/projects/llmq4/quotas", json=body)).status_code == 201


async def test_deleting_a_budget_records_what_it_was(
    login_as: LoginAs, db_session: AsyncSession
) -> None:
    """Switching a control off belongs in the audit with its former value, not merely
    as 'deleted'."""
    admin = await login_as("sub-q-5", "q5@osaip.dev")
    await _project(admin, "llmq5")
    created = await admin.post(
        "/api/v1/projects/llmq5/quotas", json={"period": "day", "limit_calls": 42}
    )
    quota_id = created.json()["id"]
    await admin.delete(f"/api/v1/projects/llmq5/quotas/{quota_id}")
    # Scoped to THIS quota: other tests delete budgets too.
    entry = (
        await db_session.execute(
            select(AuditLog).where(
                AuditLog.action == "quota.deleted", AuditLog.object_id == quota_id
            )
        )
    ).scalar_one()
    assert entry.details["limit_calls"] == 42


# ── usage ───────────────────────────────────────────────────────────────────────


async def test_usage_reports_the_ledger(login_as: LoginAs, db_session: AsyncSession) -> None:
    admin = await login_as("sub-u-1", "u1@osaip.dev")
    await _project(admin, "llmu1")
    project_id = await _project_id(db_session, "llmu1")

    db_session.add(
        LlmCall(
            id=new_id(),
            project_id=project_id,
            ts=datetime.datetime.now(datetime.UTC),
            provider="openai",
            model="gpt-4o-mini",
            purpose="general",
            tokens_in=10,
            tokens_out=5,
            cost_micros=1234,
            currency="EUR",
        )
    )
    await db_session.commit()

    response = await admin.get("/api/v1/projects/llmu1/usage?group_by=model")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"]["cost_micros"] == 1234
    assert body["currency"] == "EUR"
    assert body["pricing_incomplete"] is False
    assert [b["key"] for b in body["buckets"]] == ["gpt-4o-mini"]
    assert response.headers.get("ETag")


async def test_usage_flags_an_incomplete_total(login_as: LoginAs, db_session: AsyncSession) -> None:
    """An unpriced model contributes 0, so the total is a FLOOR — the UI must be told
    rather than presenting it as the whole spend."""
    admin = await login_as("sub-u-2", "u2@osaip.dev")
    await _project(admin, "llmu2")
    project_id = await _project_id(db_session, "llmu2")
    db_session.add(
        LlmCall(
            id=new_id(),
            project_id=project_id,
            ts=datetime.datetime.now(datetime.UTC),
            provider="ollama",
            model="some-local-model",
            purpose="general",
            cost_micros=0,
            currency="EUR",
            pricing_unknown=True,
        )
    )
    await db_session.commit()
    body = (await admin.get("/api/v1/projects/llmu2/usage")).json()
    assert body["pricing_incomplete"] is True


async def test_usage_rejects_a_silly_range(login_as: LoginAs) -> None:
    admin = await login_as("sub-u-3", "u3@osaip.dev")
    await _project(admin, "llmu3")
    response = await admin.get(
        "/api/v1/projects/llmu3/usage?from=2020-01-01T00:00:00Z&to=2026-01-01T00:00:00Z"
    )
    assert response.status_code == 422


async def test_usage_rejects_an_unknown_grouping(login_as: LoginAs) -> None:
    admin = await login_as("sub-u-4", "u4@osaip.dev")
    await _project(admin, "llmu4")
    assert (await admin.get("/api/v1/projects/llmu4/usage?group_by=nonsense")).status_code == 422


# ── prompts ─────────────────────────────────────────────────────────────────────


async def test_saving_a_prompt_twice_makes_a_version(login_as: LoginAs) -> None:
    """A prompt is part of how a decision was produced; overwriting one would erase the
    explanation of every past call that used it (AI Act Art 12)."""
    admin = await login_as("sub-p-1", "p1@osaip.dev")
    await _project(admin, "llmpr1")

    first = await admin.post(
        "/api/v1/projects/llmpr1/prompts",
        json={"name": "classify", "template": "Label the row: {row}"},
    )
    assert first.status_code == 201, first.text
    assert first.json()["version"] == 1

    second = await admin.post(
        "/api/v1/projects/llmpr1/prompts",
        json={"name": "classify", "template": "Label it carefully: {row}"},
    )
    assert second.json()["version"] == 2

    versions = await admin.get("/api/v1/projects/llmpr1/prompts/classify")
    assert [v["version"] for v in versions.json()["versions"]] == [2, 1]
    # The list shows the latest per name, not every version.
    listed = await admin.get("/api/v1/projects/llmpr1/prompts")
    assert [p["version"] for p in listed.json()["items"]] == [2]


async def test_a_template_may_not_hand_roll_the_untrusted_delimiters(
    login_as: LoginAs,
) -> None:
    """§5d: the platform wraps untrusted content. A hand-written closing tag is exactly
    what an attacker can forge."""
    admin = await login_as("sub-p-2", "p2@osaip.dev")
    await _project(admin, "llmpr2")
    response = await admin.post(
        "/api/v1/projects/llmpr2/prompts",
        json={"name": "bad", "template": "Answer using <untrusted>{cell}</untrusted>"},
    )
    assert response.status_code == 422
    assert response.json()["type"] == "urn:osaip:problem:validation"


async def test_an_unknown_prompt_is_404(login_as: LoginAs) -> None:
    admin = await login_as("sub-p-3", "p3@osaip.dev")
    await _project(admin, "llmpr3")
    assert (await admin.get("/api/v1/projects/llmpr3/prompts/nope")).status_code == 404


# ── guardrail policies ──────────────────────────────────────────────────────────


async def test_policies_are_site_admin_only(login_as: LoginAs) -> None:
    admin = await login_as("sub-gp-1", "gp1@osaip.dev")  # project admin, not site admin
    await _project(admin, "llmgp1")
    assert (await admin.get("/api/v1/guardrail-policies")).status_code == 403


async def test_a_policy_reports_its_effective_settings(
    login_as: LoginAs, db_session: AsyncSession
) -> None:
    """An operator must be able to see that PII redaction is on regardless of what the
    policy document says (BIO2 8.12)."""
    await login_as("gp-site-admin", "gpsa@osaip.dev")
    await db_session.execute(
        text("UPDATE users SET is_site_admin=true WHERE oidc_sub='gp-site-admin'")
    )
    await db_session.commit()
    site_admin = await login_as("gp-site-admin", "gpsa@osaip.dev")

    created = await site_admin.post(
        "/api/v1/guardrail-policies",
        json={
            "name": "strict",
            # Deliberately tries to switch the baseline off.
            "stages": {"pre": {"redact_pii": False, "max_input_chars": 5000}},
        },
    )
    assert created.status_code == 201, created.text
    effective = created.json()["effective"]
    assert effective["redact_pii"] is True  # not configurable away
    assert effective["max_input_chars"] == 5000
