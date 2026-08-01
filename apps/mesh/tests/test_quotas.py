"""Quota reserve/settle.

The load-bearing test is `test_concurrent_calls_cannot_overshoot`: it is the reason
reserve/settle exists at all instead of a check-then-call read.
"""

import asyncio
import datetime
import uuid
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from osaip_api.models import LlmCall, Notification, Quota, QuotaReservation
from osaip_mesh.quotas import (
    RESERVATION_TTL,
    QuotaExceeded,
    Reservation,
    Scope,
    reserve,
    settle,
    window_start,
)
from osaip_shared.ids import new_id


async def _quota(session: AsyncSession, scope: Scope, **overrides: Any) -> Quota:
    quota = Quota(
        id=new_id(),
        scope_type=scope.scope_type,
        scope_id=scope.scope_id,
        period=overrides.pop("period", "month"),
        limit_cost_micros=overrides.pop("limit_cost_micros", 1_000),
        limit_calls=overrides.pop("limit_calls", None),
        action=overrides.pop("action", "block"),
    )
    session.add(quota)
    await session.commit()
    return quota


def _scope() -> Scope:
    return Scope("project", new_id())


# ── window maths ─────────────────────────────────────────────────────────────────


def test_windows_are_calendar_aligned() -> None:
    """A monthly budget resets on the 1st, not 30 days after it was created."""
    now = datetime.datetime(2026, 8, 17, 14, 30, tzinfo=datetime.UTC)
    assert window_start("day", now) == datetime.datetime(2026, 8, 17, tzinfo=datetime.UTC)
    assert window_start("month", now) == datetime.datetime(2026, 8, 1, tzinfo=datetime.UTC)


# ── reserve / settle ─────────────────────────────────────────────────────────────


async def test_no_quota_means_no_reservation(mesh_session: AsyncSession) -> None:
    reservation = await reserve(mesh_session, scopes=[_scope()], estimated_micros=500)
    assert reservation.ids == []
    assert reservation.warnings == []


async def test_reserve_holds_and_settle_releases(mesh_session: AsyncSession) -> None:
    scope = _scope()
    await _quota(mesh_session, scope, limit_cost_micros=10_000)

    reservation = await reserve(mesh_session, scopes=[scope], estimated_micros=4_000)
    assert len(reservation.ids) == 1
    held = await mesh_session.get(QuotaReservation, reservation.ids[0])
    assert held is not None
    assert held.estimated_micros == 4_000
    assert held.settled_micros is None  # open: still counts against the window

    call_id = new_id()
    await settle(mesh_session, reservation, actual_micros=120, call_id=call_id)
    await mesh_session.commit()
    await mesh_session.refresh(held)
    assert held.settled_micros == 120
    assert held.call_id == call_id


async def test_blocking_quota_raises_and_leaves_no_hold(mesh_session: AsyncSession) -> None:
    scope = _scope()
    await _quota(mesh_session, scope, limit_cost_micros=100, action="block")

    with pytest.raises(QuotaExceeded) as excinfo:
        await reserve(mesh_session, scopes=[scope], estimated_micros=500)
    assert excinfo.value.status.exceeded_dimension == "cost"

    # A refused call must not leave a hold behind, or the budget would leak.
    count = (
        await mesh_session.execute(
            select(func.count())
            .select_from(QuotaReservation)
            .where(QuotaReservation.scope_id == scope.scope_id)
        )
    ).scalar_one()
    assert count == 0


async def test_warning_quota_allows_the_call(mesh_session: AsyncSession) -> None:
    scope = _scope()
    await _quota(mesh_session, scope, limit_cost_micros=100, action="warn")
    reservation = await reserve(mesh_session, scopes=[scope], estimated_micros=500)
    assert len(reservation.ids) == 1
    assert len(reservation.warnings) == 1
    assert reservation.warnings[0].just_crossed is True


async def test_warning_reports_the_crossing_only_once(mesh_session: AsyncSession) -> None:
    """A warn budget keeps letting calls through; only the call that crosses is news."""
    scope = _scope()
    await _quota(mesh_session, scope, limit_cost_micros=100, action="warn")

    first = await reserve(mesh_session, scopes=[scope], estimated_micros=500)
    assert first.warnings[0].just_crossed is True
    second = await reserve(mesh_session, scopes=[scope], estimated_micros=500)
    assert second.warnings[0].just_crossed is False


async def test_call_limits_are_enforced_too(mesh_session: AsyncSession) -> None:
    scope = _scope()
    await _quota(mesh_session, scope, limit_cost_micros=None, limit_calls=1, action="block")
    await reserve(mesh_session, scopes=[scope], estimated_micros=0)
    with pytest.raises(QuotaExceeded) as excinfo:
        await reserve(mesh_session, scopes=[scope], estimated_micros=0)
    assert excinfo.value.status.exceeded_dimension == "calls"


async def test_settled_reservations_stop_double_counting(
    mesh_session: AsyncSession, make_project: Any
) -> None:
    """Once settled, the ledger row is the truth — counting the hold as well would
    charge the window twice for one call."""
    project = await make_project()
    await mesh_session.commit()
    scope = Scope("project", project.id)
    await _quota(mesh_session, scope, limit_cost_micros=1_000, action="block")

    reservation = await reserve(mesh_session, scopes=[scope], estimated_micros=900)
    mesh_session.add(
        LlmCall(
            id=new_id(),
            project_id=scope.scope_id,
            provider="echo",
            model="echo-1",
            purpose="general",
            cost_micros=10,
            currency="EUR",
        )
    )
    await settle(mesh_session, reservation, actual_micros=10, call_id=None)
    await mesh_session.commit()

    # Spend is now 10 (the ledger), not 900 (the hold) — so a 900 call still fits.
    again = await reserve(mesh_session, scopes=[scope], estimated_micros=900)
    assert len(again.ids) == 1


async def test_reservations_outside_the_window_are_ignored(mesh_session: AsyncSession) -> None:
    scope = _scope()
    await _quota(mesh_session, scope, period="day", limit_cost_micros=1_000, action="block")
    mesh_session.add(
        QuotaReservation(
            id=new_id(),
            scope_type=scope.scope_type,
            scope_id=scope.scope_id,
            ts=datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=2),
            estimated_micros=999_999,
        )
    )
    await mesh_session.commit()
    reservation = await reserve(mesh_session, scopes=[scope], estimated_micros=100)
    assert len(reservation.ids) == 1  # yesterday's spend is not today's problem


async def test_an_abandoned_hold_stops_blocking_the_budget(mesh_session: AsyncSession) -> None:
    """A process that dies between reserve and settle leaves an open hold. Without a
    TTL that hold would keep the budget full until the window rolled — a month."""
    scope = _scope()
    await _quota(mesh_session, scope, limit_cost_micros=1_000, action="block")
    mesh_session.add(
        QuotaReservation(
            id=new_id(),
            scope_type=scope.scope_type,
            scope_id=scope.scope_id,
            ts=datetime.datetime.now(datetime.UTC)
            - RESERVATION_TTL
            - datetime.timedelta(minutes=1),
            estimated_micros=999_999,
            settled_micros=None,
        )
    )
    await mesh_session.commit()
    reservation = await reserve(mesh_session, scopes=[scope], estimated_micros=900)
    assert len(reservation.ids) == 1


async def test_a_fresh_hold_still_blocks(mesh_session: AsyncSession) -> None:
    """The TTL must not be so eager that a call in flight stops counting."""
    scope = _scope()
    await _quota(mesh_session, scope, limit_cost_micros=1_000, action="block")
    mesh_session.add(
        QuotaReservation(
            id=new_id(),
            scope_type=scope.scope_type,
            scope_id=scope.scope_id,
            ts=datetime.datetime.now(datetime.UTC) - datetime.timedelta(seconds=30),
            estimated_micros=999_999,
        )
    )
    await mesh_session.commit()
    with pytest.raises(QuotaExceeded):
        await reserve(mesh_session, scopes=[scope], estimated_micros=900)


async def test_a_call_can_be_under_several_budgets(mesh_session: AsyncSession) -> None:
    project, connection = Scope("project", new_id()), Scope("connection", new_id())
    await _quota(mesh_session, project, limit_cost_micros=10_000)
    await _quota(mesh_session, connection, limit_cost_micros=50, action="block")

    # The connection budget is the tighter one and must still bite.
    with pytest.raises(QuotaExceeded) as excinfo:
        await reserve(mesh_session, scopes=[project, connection], estimated_micros=100)
    assert excinfo.value.status.scope_type == "connection"


async def test_settle_is_a_no_op_without_a_reservation(mesh_session: AsyncSession) -> None:
    await settle(mesh_session, Reservation(), actual_micros=10, call_id=None)


async def test_concurrent_calls_cannot_overshoot(mesh_app: Any) -> None:
    """The reason reserve/settle exists: with a plain check-then-call, ten concurrent
    calls all read the same 'spent so far', all pass, and the budget blows through."""
    scope = Scope("project", new_id())
    maker = mesh_app.state.sessionmaker
    async with maker() as setup:
        setup.add(
            Quota(
                id=new_id(),
                scope_type=scope.scope_type,
                scope_id=scope.scope_id,
                period="month",
                limit_cost_micros=1_000,
                action="block",
            )
        )
        await setup.commit()

    async def attempt() -> bool:
        # A separate session per task: concurrency through one session proves nothing.
        async with maker() as session:
            try:
                await reserve(session, scopes=[scope], estimated_micros=200)
            except QuotaExceeded:
                return False
            return True

    results = await asyncio.gather(*(attempt() for _ in range(10)))

    async with maker() as check:
        held = (
            await check.execute(
                select(func.coalesce(func.sum(QuotaReservation.estimated_micros), 0)).where(
                    QuotaReservation.scope_id == scope.scope_id
                )
            )
        ).scalar_one()
    # 5 × 200 fits in 1000; the 6th would exceed it. Never more than the budget.
    assert sum(results) == 5
    assert held == 1_000


# ── through the HTTP surface ─────────────────────────────────────────────────────


async def test_quota_block_is_429_with_its_own_slug(
    mesh_client: httpx.AsyncClient, mesh_session: AsyncSession, make_connection: Any
) -> None:
    """A budget block must be distinguishable from a provider rate-limit: one is worth
    retrying, the other is not."""
    connection = await make_connection()
    mesh_session.add(
        Quota(
            id=new_id(),
            scope_type="connection",
            scope_id=connection.id,
            period="month",
            limit_calls=0,
            action="block",
        )
    )
    await mesh_session.commit()

    response = await mesh_client.post(
        "/v1/complete",
        json={
            "connection_id": str(connection.id),
            "model": "echo-1",
            "messages": [{"role": "user", "content": "hi"}],
            "max_classification": "none",
        },
    )
    assert response.status_code == 429
    body = response.json()
    assert body["type"] == "urn:osaip:problem:quota-exceeded"
    assert body["scope_type"] == "connection"
    assert body["dimension"] == "calls"
    assert body["hint"]

    # Blocked before the provider ran: nothing was ledgered.
    count = (
        await mesh_session.execute(
            select(func.count()).select_from(LlmCall).where(LlmCall.connection_id == connection.id)
        )
    ).scalar_one()
    assert count == 0


async def test_warn_quota_returns_a_header_and_notifies_once(
    mesh_client: httpx.AsyncClient,
    mesh_session: AsyncSession,
    make_connection: Any,
    make_user: Any,
) -> None:
    connection = await make_connection()
    user = await make_user()
    mesh_session.add(
        Quota(
            id=new_id(),
            scope_type="connection",
            scope_id=connection.id,
            period="month",
            limit_calls=0,
            action="warn",
        )
    )
    await mesh_session.commit()

    payload = {
        "connection_id": str(connection.id),
        "model": "echo-1",
        "messages": [{"role": "user", "content": "hi"}],
        "max_classification": "none",
        "user_id": str(user.id),
    }
    first = await mesh_client.post("/v1/complete", json=payload)
    assert first.status_code == 200  # warn lets the call through
    assert "connection:calls" in first.headers["X-OSAIP-Quota-Warning"]
    assert first.json()["quota_warnings"][0]["dimension"] == "calls"

    await mesh_client.post("/v1/complete", json=payload)

    # Notified once, on the crossing — not on every call while over the line.
    notifications = (
        (
            await mesh_session.execute(
                select(Notification).where(
                    Notification.user_id == user.id, Notification.kind == "quota.warning"
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(notifications) == 1
    assert notifications[0].severity == "warning"


async def test_settled_reservation_matches_the_ledger_after_a_real_call(
    mesh_client: httpx.AsyncClient, mesh_session: AsyncSession, make_connection: Any
) -> None:
    connection = await make_connection()
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

    body = (
        await mesh_client.post(
            "/v1/complete",
            json={
                "connection_id": str(connection.id),
                "model": "echo-1",
                "messages": [{"role": "user", "content": "hello there"}],
                "max_classification": "none",
            },
        )
    ).json()

    held = (
        await mesh_session.execute(
            select(QuotaReservation).where(QuotaReservation.scope_id == connection.id)
        )
    ).scalar_one()
    assert held.settled_micros == body["cost_micros"]
    assert held.call_id == uuid.UUID(body["call_id"])
    assert held.estimated_micros >= held.settled_micros  # the hold was the worst case


async def test_no_notification_without_a_user(
    mesh_client: httpx.AsyncClient, mesh_session: AsyncSession, make_connection: Any
) -> None:
    """A system call has no one to notify; it must not invent a recipient."""
    connection = await make_connection()
    mesh_session.add(
        Quota(
            id=new_id(),
            scope_type="connection",
            scope_id=connection.id,
            period="month",
            limit_calls=0,
            action="warn",
        )
    )
    await mesh_session.commit()
    before = (
        await mesh_session.execute(select(func.count()).select_from(Notification))
    ).scalar_one()

    await mesh_client.post(
        "/v1/complete",
        json={
            "connection_id": str(connection.id),
            "model": "echo-1",
            "messages": [{"role": "user", "content": "hi"}],
            "max_classification": "none",
        },
    )
    after = (
        await mesh_session.execute(select(func.count()).select_from(Notification))
    ).scalar_one()
    assert after == before
