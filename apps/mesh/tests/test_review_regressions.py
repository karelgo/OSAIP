"""Regression tests for the defects the Phase 3a adversarial review confirmed.

Each test names the defect it locks down. They live together because they share one
lesson: a call that reached the provider must ALWAYS end up in the ledger with its hold
settled, no matter which exit the code takes afterwards.
"""

import uuid
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from osaip_api.models import GuardrailPolicy, LlmCall, LlmCallMessage, Quota, QuotaReservation
from osaip_mesh.ledger import ensure_trace
from osaip_mesh.quotas import Scope, reserve
from osaip_shared.ids import new_id

SCHEMA_POLICY = {"post": {"schema": {"type": "object", "required": ["label"]}}}


async def _blocking_policy(session: AsyncSession) -> GuardrailPolicy:
    policy = GuardrailPolicy(
        id=new_id(), project_id=None, name=f"shape-{uuid.uuid4().hex[:6]}", stages=SCHEMA_POLICY
    )
    session.add(policy)
    await session.commit()
    return policy


# ── [1]/[4] a post-guardrail rejection must still settle ────────────────────────


async def test_post_rejection_still_writes_a_ledger_row(
    mesh_client: httpx.AsyncClient, mesh_session: AsyncSession, make_connection: Any
) -> None:
    """The provider already ran and billed. Dropping the ledger row would make usage
    reporting under-count real spend, permanently."""
    policy = await _blocking_policy(mesh_session)
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

    call = (
        await mesh_session.execute(select(LlmCall).where(LlmCall.connection_id == connection.id))
    ).scalar_one()
    assert call.status == "blocked"
    assert call.tokens_in > 0  # the call really happened


async def test_post_rejection_settles_its_quota_hold(
    mesh_client: httpx.AsyncClient, mesh_session: AsyncSession, make_connection: Any
) -> None:
    """An unsettled hold keeps the budget artificially full until the TTL expires."""
    policy = await _blocking_policy(mesh_session)
    connection = await make_connection(guardrail_policy_id=policy.id)
    mesh_session.add(
        Quota(
            id=new_id(),
            scope_type="connection",
            scope_id=connection.id,
            period="month",
            limit_cost_micros=1_000_000,
            action="block",
        )
    )
    await mesh_session.commit()

    await mesh_client.post(
        "/v1/complete",
        json={
            "connection_id": str(connection.id),
            "model": "echo-1",
            "messages": [{"role": "user", "content": "classify this"}],
            "max_classification": "none",
        },
    )
    held = (
        await mesh_session.execute(
            select(QuotaReservation).where(QuotaReservation.scope_id == connection.id)
        )
    ).scalar_one()
    assert held.settled_micros is not None  # not left open
    assert held.call_id is not None  # and linked to the ledger row


async def test_a_rejected_answer_is_never_stored_or_cached(
    mesh_client: httpx.AsyncClient, mesh_session: AsyncSession, make_connection: Any
) -> None:
    """The policy said the response must not be used; storing or serving it anyway
    would defeat the block."""
    policy = await _blocking_policy(mesh_session)
    connection = await make_connection(guardrail_policy_id=policy.id, cache_ttl_s=300)

    payload = {
        "connection_id": str(connection.id),
        "model": "echo-1",
        "messages": [{"role": "user", "content": "classify this"}],
        "max_classification": "none",
    }
    await mesh_client.post("/v1/complete", json=payload)
    call = (
        await mesh_session.execute(select(LlmCall).where(LlmCall.connection_id == connection.id))
    ).scalar_one()
    roles = (
        (
            await mesh_session.execute(
                select(LlmCallMessage.role).where(LlmCallMessage.call_id == call.id)
            )
        )
        .scalars()
        .all()
    )
    assert "assistant" not in roles  # the refused answer was not audited

    # And the second identical call must not be served the refused answer from cache.
    again = await mesh_client.post("/v1/complete", json=payload)
    assert again.status_code == 422


# ── [3] concurrent calls sharing a caller-supplied trace ────────────────────────


async def test_concurrent_calls_can_share_one_caller_supplied_trace(
    mesh_session: AsyncSession,
) -> None:
    """A per-row build fires many calls under one trace_id; check-then-insert let two
    of them both see 'absent' and one die on the primary key."""
    trace_id = new_id()
    first = await ensure_trace(mesh_session, trace_id, root_kind="recipe")
    second = await ensure_trace(mesh_session, trace_id, root_kind="recipe")
    await mesh_session.commit()
    assert first == second == trace_id


async def test_ensure_trace_survives_a_row_inserted_underneath_it(
    mesh_app: Any,
) -> None:
    """The race in full: another session commits the same trace between our read and
    our insert. ON CONFLICT DO NOTHING makes that a no-op instead of a crash."""
    trace_id = new_id()
    maker = mesh_app.state.sessionmaker
    async with maker() as other:
        await ensure_trace(other, trace_id, root_kind="recipe")
        await other.commit()
    async with maker() as mine:
        assert await ensure_trace(mine, trace_id, root_kind="recipe") == trace_id
        await mine.commit()


# ── [5] a scope may carry both a daily and a monthly budget ─────────────────────


async def test_a_daily_budget_is_enforced_alongside_a_monthly_one(
    mesh_session: AsyncSession, make_project: Any
) -> None:
    """`uq_quotas_scope_period` permits both; keying the lookup by scope alone silently
    dropped one, so the tighter cap was never enforced."""
    project = await make_project()
    await mesh_session.commit()
    scope = Scope("project", project.id)
    mesh_session.add_all(
        [
            Quota(
                id=new_id(),
                scope_type="project",
                scope_id=project.id,
                period="month",
                limit_calls=1_000,
                action="block",
            ),
            Quota(
                id=new_id(),
                scope_type="project",
                scope_id=project.id,
                period="day",
                limit_calls=0,  # the tight one
                action="block",
            ),
        ]
    )
    await mesh_session.commit()

    from osaip_mesh.quotas import QuotaExceeded

    with pytest.raises(QuotaExceeded) as excinfo:
        await reserve(mesh_session, scopes=[scope], estimated_micros=0)
    assert excinfo.value.status.period == "day"


async def test_one_hold_per_scope_not_per_budget(
    mesh_session: AsyncSession, make_project: Any
) -> None:
    """Two budgets on one scope must not double-charge the window."""
    project = await make_project()
    await mesh_session.commit()
    scope = Scope("project", project.id)
    mesh_session.add_all(
        [
            Quota(
                id=new_id(),
                scope_type="project",
                scope_id=project.id,
                period=period,
                limit_cost_micros=1_000_000,
                action="block",
            )
            for period in ("day", "month")
        ]
    )
    await mesh_session.commit()

    reservation = await reserve(mesh_session, scopes=[scope], estimated_micros=100)
    assert len(reservation.ids) == 1
    count = (
        await mesh_session.execute(
            select(func.count())
            .select_from(QuotaReservation)
            .where(QuotaReservation.scope_id == project.id)
        )
    ).scalar_one()
    assert count == 1
