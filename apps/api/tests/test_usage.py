"""Usage rollups over the LLM ledger — the numbers behind the Usage panel."""

import datetime
import uuid
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from osaip_api.models import LlmCall, Project
from osaip_api.usage import usage_report
from osaip_shared.ids import new_id

NOW = datetime.datetime(2026, 8, 15, 12, 0, tzinfo=datetime.UTC)


async def _project(session: AsyncSession) -> Project:
    project = Project(id=new_id(), key=f"u{uuid.uuid4().hex[:8]}", name="usage", storage_prefix="u")
    session.add(project)
    await session.flush()
    return project


def _call(project_id: uuid.UUID, **overrides: Any) -> LlmCall:
    defaults: dict[str, Any] = {
        "id": new_id(),
        "project_id": project_id,
        "ts": NOW,
        "provider": "echo",
        "model": "echo-1",
        "purpose": "general",
        "tokens_in": 10,
        "tokens_out": 5,
        "cost_micros": 100,
        "currency": "EUR",
        "status": "ok",
        "cache_hit": False,
    }
    defaults.update(overrides)
    return LlmCall(**defaults)


async def _seed(session: AsyncSession, *calls: LlmCall) -> None:
    session.add_all(calls)
    await session.commit()


async def test_totals_sum_the_window(db_session: AsyncSession) -> None:
    project = await _project(db_session)
    await _seed(
        db_session,
        _call(project.id, cost_micros=100),
        _call(project.id, cost_micros=250, tokens_in=20, tokens_out=8),
    )
    report = await usage_report(
        db_session,
        project_id=project.id,
        from_ts=NOW - datetime.timedelta(days=1),
        to_ts=NOW + datetime.timedelta(days=1),
    )
    assert report.total.calls == 2
    assert report.total.cost_micros == 350
    assert report.total.tokens_in == 30
    assert report.total.tokens_out == 13
    assert report.currency == "EUR"


async def test_window_is_half_open(db_session: AsyncSession) -> None:
    """Adjacent windows must tile without counting a boundary call twice."""
    project = await _project(db_session)
    await _seed(db_session, _call(project.id, ts=NOW))
    included = await usage_report(
        db_session, project_id=project.id, from_ts=NOW, to_ts=NOW + datetime.timedelta(hours=1)
    )
    excluded = await usage_report(
        db_session, project_id=project.id, from_ts=NOW - datetime.timedelta(hours=1), to_ts=NOW
    )
    assert included.total.calls == 1
    assert excluded.total.calls == 0


async def test_another_projects_spend_is_invisible(db_session: AsyncSession) -> None:
    mine, theirs = await _project(db_session), await _project(db_session)
    await _seed(db_session, _call(mine.id, cost_micros=100), _call(theirs.id, cost_micros=9_999))
    report = await usage_report(
        db_session,
        project_id=mine.id,
        from_ts=NOW - datetime.timedelta(days=1),
        to_ts=NOW + datetime.timedelta(days=1),
    )
    assert report.total.cost_micros == 100


@pytest.mark.parametrize(
    ("group_by", "expected"),
    [
        ("model", {"echo-1": 100, "echo-2": 250}),
        ("provider", {"echo": 100, "ollama": 250}),
        ("purpose", {"general": 100, "guardrail": 250}),
    ],
)
async def test_grouping_dimensions(
    db_session: AsyncSession, group_by: Any, expected: dict[str, int]
) -> None:
    project = await _project(db_session)
    await _seed(
        db_session,
        _call(project.id, cost_micros=100),
        _call(
            project.id,
            cost_micros=250,
            model="echo-2",
            provider="ollama",
            purpose="guardrail",
        ),
    )
    report = await usage_report(
        db_session,
        project_id=project.id,
        from_ts=NOW - datetime.timedelta(days=1),
        to_ts=NOW + datetime.timedelta(days=1),
        group_by=group_by,
    )
    assert {b.key: b.cost_micros for b in report.buckets} == expected


async def test_grouping_by_day_uses_dates(db_session: AsyncSession) -> None:
    project = await _project(db_session)
    await _seed(
        db_session,
        _call(project.id, ts=NOW, cost_micros=100),
        _call(project.id, ts=NOW - datetime.timedelta(days=1), cost_micros=50),
    )
    report = await usage_report(
        db_session,
        project_id=project.id,
        from_ts=NOW - datetime.timedelta(days=3),
        to_ts=NOW + datetime.timedelta(days=1),
        group_by="day",
    )
    assert [b.key for b in report.buckets] == ["2026-08-14", "2026-08-15"]
    assert [b.cost_micros for b in report.buckets] == [50, 100]


async def test_calls_without_a_user_are_labelled_not_dropped(db_session: AsyncSession) -> None:
    """A system call still costs money; hiding it would make the panel not add up."""
    project = await _project(db_session)
    await _seed(db_session, _call(project.id, user_id=None, cost_micros=100))
    report = await usage_report(
        db_session,
        project_id=project.id,
        from_ts=NOW - datetime.timedelta(days=1),
        to_ts=NOW + datetime.timedelta(days=1),
        group_by="user",
    )
    assert [b.key for b in report.buckets] == ["unattributed"]
    assert report.total.cost_micros == 100


async def test_cache_hits_and_errors_are_counted_separately(db_session: AsyncSession) -> None:
    project = await _project(db_session)
    await _seed(
        db_session,
        _call(project.id, cache_hit=True, cost_micros=0),
        _call(project.id, status="error", cost_micros=0),
        _call(project.id, cost_micros=100),
    )
    report = await usage_report(
        db_session,
        project_id=project.id,
        from_ts=NOW - datetime.timedelta(days=1),
        to_ts=NOW + datetime.timedelta(days=1),
    )
    assert report.total.calls == 3
    assert report.total.cache_hits == 1
    assert report.total.errors == 1
    assert report.total.cost_micros == 100


async def test_unpriced_models_flag_the_total_as_incomplete(db_session: AsyncSession) -> None:
    """An unpriced model contributes 0; the total is then a floor, and the report must
    say so rather than let the UI present it as the whole spend."""
    project = await _project(db_session)
    await _seed(db_session, _call(project.id, cost_micros=0, pricing_unknown=True))
    report = await usage_report(
        db_session,
        project_id=project.id,
        from_ts=NOW - datetime.timedelta(days=1),
        to_ts=NOW + datetime.timedelta(days=1),
    )
    assert report.pricing_incomplete is True


async def test_an_empty_window_reports_zeroes(db_session: AsyncSession) -> None:
    project = await _project(db_session)
    await db_session.commit()
    report = await usage_report(
        db_session,
        project_id=project.id,
        from_ts=NOW - datetime.timedelta(days=1),
        to_ts=NOW + datetime.timedelta(days=1),
    )
    assert report.buckets == []
    assert report.total.calls == 0
    assert report.total.cost_micros == 0
    assert report.pricing_incomplete is False
