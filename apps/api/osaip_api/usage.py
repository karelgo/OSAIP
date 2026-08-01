"""Usage rollups over the LLM ledger (spec §4, ADR-0008 §8).

Aggregation happens in SQL, never by loading rows into Python: a busy project's ledger
is one row per model call — per input row for a per-row build — and pulling that into
memory to sum it would fall over exactly when the panel matters most.

Costs stay integer micros end to end. The UI formats them for display; nothing here
converts to a float, because summing floats over a month drifts.
"""

import datetime
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from osaip_api.models import LlmCall

GroupBy = Literal["day", "model", "user", "provider", "purpose"]
GROUP_BY_VALUES: tuple[GroupBy, ...] = ("day", "model", "user", "provider", "purpose")


@dataclass
class UsageBucket:
    key: str
    calls: int
    tokens_in: int
    tokens_out: int
    cost_micros: int
    cache_hits: int
    errors: int


@dataclass
class UsageReport:
    from_ts: datetime.datetime
    to_ts: datetime.datetime
    group_by: GroupBy
    currency: str
    total: UsageBucket
    buckets: list[UsageBucket]
    # True when any call in the range used a model with no pinned price: the total is
    # then a floor, not the whole spend, and the UI must say so rather than imply exact.
    pricing_incomplete: bool


# Returns Any rather than ColumnElement: SQLAlchemy's stubs type a mapped attribute as
# InstrumentedAttribute[str], which does not unify with ColumnElement[Any] across the
# branches. The value only ever flows into select()/group_by(), which validate it.
def _group_expression(group_by: GroupBy) -> Any:
    match group_by:
        case "day":
            return func.date_trunc("day", LlmCall.ts)
        case "model":
            return LlmCall.model
        case "user":
            return LlmCall.user_id
        case "provider":
            return LlmCall.provider
        case "purpose":
            return LlmCall.purpose


def _bucket_key(group_by: GroupBy, value: object) -> str:
    if value is None:
        return "unattributed"  # e.g. a system call with no user
    if group_by == "day" and isinstance(value, datetime.datetime):
        return value.date().isoformat()
    return str(value)


def _bucket(key: str, measures: Sequence[Any]) -> UsageBucket:
    calls, tokens_in, tokens_out, cost_micros, cache_hits, errors = measures
    return UsageBucket(
        key=key,
        calls=int(calls),
        tokens_in=int(tokens_in),
        tokens_out=int(tokens_out),
        cost_micros=int(cost_micros),
        cache_hits=int(cache_hits),
        errors=int(errors),
    )


async def usage_report(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    from_ts: datetime.datetime,
    to_ts: datetime.datetime,
    group_by: GroupBy = "day",
    currency: str = "EUR",
) -> UsageReport:
    """Spend and volume for one project over a half-open window [from_ts, to_ts).

    Half-open so adjacent windows tile without double-counting a call that lands
    exactly on a boundary.
    """
    grouping = _group_expression(group_by)
    scope = (
        LlmCall.project_id == project_id,
        LlmCall.ts >= from_ts,
        LlmCall.ts < to_ts,
    )
    measures = (
        func.count(),
        func.coalesce(func.sum(LlmCall.tokens_in), 0),
        func.coalesce(func.sum(LlmCall.tokens_out), 0),
        func.coalesce(func.sum(LlmCall.cost_micros), 0),
        func.count().filter(LlmCall.cache_hit.is_(True)),
        func.count().filter(LlmCall.status != "ok"),
    )
    rows = (
        await session.execute(
            select(grouping, *measures).where(*scope).group_by(grouping).order_by(grouping)
        )
    ).all()
    totals = (await session.execute(select(*measures).where(*scope))).one()
    unpriced = (
        await session.execute(select(func.count()).where(*scope, LlmCall.pricing_unknown.is_(True)))
    ).scalar_one()

    return UsageReport(
        from_ts=from_ts,
        to_ts=to_ts,
        group_by=group_by,
        currency=currency,
        total=_bucket("total", totals),
        buckets=[_bucket(_bucket_key(group_by, row[0]), row[1:]) for row in rows],
        pricing_incomplete=bool(unpriced),
    )
