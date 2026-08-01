"""Budget enforcement by reserve/settle (ADR-0008 §3).

A check-then-call quota is racy: N concurrent calls all read the same "spent so far",
all pass, and the budget overshoots by N-1 calls. So a call first RESERVES its worst
case (the estimated max cost) in a short committed transaction; the reservation is
visible to every concurrent caller's window sum, so parallel calls cannot collectively
overshoot. After the call the reservation is SETTLED to the actual cost — including 0
for a cache hit or a failed call, which releases the hold.

Spend in a window is therefore `sum(ledger) + sum(open reservations)`: a settled
reservation is excluded because its ledger row already accounts for it.
"""

import datetime
import uuid
from dataclasses import dataclass, field

from sqlalchemy import Select, func, select, text, tuple_, update
from sqlalchemy.ext.asyncio import AsyncSession

from osaip_api.models import LlmCall, Quota, QuotaReservation
from osaip_shared.ids import new_id

# Locking every scope in one deterministic order keeps two calls that share scopes from
# deadlocking against each other.
_SCOPE_ORDER = ("project", "user", "connection", "agent")

_LOCK_SQL = text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))")

# How long a hold may stay open before it is assumed abandoned. Comfortably longer than
# any single model call (including provider retries), and far shorter than a budget
# window, so a crashed process costs minutes of headroom rather than a month of it.
RESERVATION_TTL = datetime.timedelta(minutes=15)


@dataclass(frozen=True)
class Scope:
    scope_type: str
    scope_id: uuid.UUID

    @property
    def lock_key(self) -> str:
        return f"osaip_quota:{self.scope_type}:{self.scope_id}"


@dataclass
class QuotaStatus:
    """A quota and where the window currently stands against it."""

    scope_type: str
    scope_id: uuid.UUID
    period: str
    action: str
    window_start: datetime.datetime
    spent_micros: int
    calls: int
    limit_cost_micros: int | None
    limit_calls: int | None
    # What THIS call added to the window, so a crossing can be told from a steady state.
    reserved_micros: int = 0

    @property
    def exceeded_dimension(self) -> str | None:
        if self.limit_cost_micros is not None and self.spent_micros > self.limit_cost_micros:
            return "cost"
        if self.limit_calls is not None and self.calls > self.limit_calls:
            return "calls"
        return None

    @property
    def just_crossed(self) -> bool:
        """True only for the call that takes the window over the line. A `warn` budget
        keeps letting calls through, so notifying on every one of them would be noise —
        the operator wants to hear about it once."""
        dimension = self.exceeded_dimension
        if dimension == "cost" and self.limit_cost_micros is not None:
            return self.spent_micros - self.reserved_micros <= self.limit_cost_micros
        if dimension == "calls" and self.limit_calls is not None:
            return self.calls - 1 <= self.limit_calls
        return False


@dataclass
class Reservation:
    """What settle() needs to close out the hold."""

    ids: list[uuid.UUID] = field(default_factory=list)
    warnings: list[QuotaStatus] = field(default_factory=list)


class QuotaExceeded(Exception):
    """A budget with action='block' would be exceeded by this call. Deliberately NOT a
    provider rate-limit: the caller must be able to tell 'you are out of budget' from
    'the provider is throttling', because only one of them is worth retrying."""

    def __init__(self, status: QuotaStatus) -> None:
        super().__init__("Quota exceeded")
        self.status = status


def window_start(period: str, now: datetime.datetime) -> datetime.datetime:
    """Budgets run on calendar windows, so a 'monthly' budget resets on the 1st rather
    than 30 days after whenever the quota happened to be created."""
    if period == "day":
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _scope_filter(statement: Select[tuple[int, int]], scope: Scope) -> Select[tuple[int, int]]:
    column = {
        "project": LlmCall.project_id,
        "user": LlmCall.user_id,
        "connection": LlmCall.connection_id,
        "agent": LlmCall.agent_id,
    }[scope.scope_type]
    return statement.where(column == scope.scope_id)


async def _window_usage(
    session: AsyncSession, scope: Scope, since: datetime.datetime, now: datetime.datetime
) -> tuple[int, int]:
    """(spent_micros, calls) = settled ledger + still-open reservations.

    A reservation whose process died never settles. Counting it forever would hold that
    budget hostage until the window rolled — up to a month. So a hold older than
    RESERVATION_TTL is treated as abandoned on READ, which self-heals whether or not
    the worker sweep ever runs.
    """
    abandoned_before = now - RESERVATION_TTL
    ledger = (
        await session.execute(
            _scope_filter(
                select(func.coalesce(func.sum(LlmCall.cost_micros), 0), func.count()).where(
                    LlmCall.ts >= since
                ),
                scope,
            )
        )
    ).one()
    held = (
        await session.execute(
            select(
                func.coalesce(func.sum(QuotaReservation.estimated_micros), 0), func.count()
            ).where(
                QuotaReservation.scope_type == scope.scope_type,
                QuotaReservation.scope_id == scope.scope_id,
                QuotaReservation.ts >= since,
                QuotaReservation.ts > abandoned_before,
                QuotaReservation.settled_micros.is_(None),
            )
        )
    ).one()
    return int(ledger[0]) + int(held[0]), int(ledger[1]) + int(held[1])


async def reserve(
    session: AsyncSession,
    *,
    scopes: list[Scope],
    estimated_micros: int,
    now: datetime.datetime | None = None,
) -> Reservation:
    """Hold `estimated_micros` against every scope that has a quota, and COMMIT.

    The commit is the point: the hold must be visible to concurrent callers before this
    call reaches the provider. Raises QuotaExceeded (leaving no hold) on a blocking
    budget; a `warn` budget only reports.
    """
    now = now or datetime.datetime.now(datetime.UTC)
    ordered = sorted(scopes, key=lambda s: (_SCOPE_ORDER.index(s.scope_type), str(s.scope_id)))
    reservation = Reservation()
    if not ordered:
        return reservation

    # Matched as pairs: an `in_` on each column separately would also match a quota
    # whose type belongs to one scope and whose id belongs to another.
    quotas = (
        (
            await session.execute(
                select(Quota).where(
                    tuple_(Quota.scope_type, Quota.scope_id).in_(
                        [(s.scope_type, s.scope_id) for s in ordered]
                    )
                )
            )
        )
        .scalars()
        .all()
    )
    by_scope = {(q.scope_type, q.scope_id): q for q in quotas}

    pending: list[tuple[Scope, QuotaStatus]] = []
    for scope in ordered:
        quota = by_scope.get((scope.scope_type, scope.scope_id))
        if quota is None:
            continue
        # Serialize every writer against this scope until we commit, so the sum we read
        # cannot go stale between the read and our insert.
        await session.execute(_LOCK_SQL, {"key": scope.lock_key})
        since = window_start(quota.period, now)
        spent, calls = await _window_usage(session, scope, since, now)
        status = QuotaStatus(
            scope_type=scope.scope_type,
            scope_id=scope.scope_id,
            period=quota.period,
            action=quota.action,
            window_start=since,
            spent_micros=spent + estimated_micros,
            calls=calls + 1,
            limit_cost_micros=quota.limit_cost_micros,
            limit_calls=quota.limit_calls,
            reserved_micros=estimated_micros,
        )
        if status.exceeded_dimension is not None:
            if quota.action == "block":
                await session.rollback()  # release the locks; leave no hold behind
                raise QuotaExceeded(status)
            reservation.warnings.append(status)
        pending.append((scope, status))

    for scope, _ in pending:
        row_id = new_id()
        session.add(
            QuotaReservation(
                id=row_id,
                scope_type=scope.scope_type,
                scope_id=scope.scope_id,
                ts=now,
                estimated_micros=estimated_micros,
            )
        )
        reservation.ids.append(row_id)
    await session.commit()
    return reservation


async def settle(
    session: AsyncSession,
    reservation: Reservation,
    *,
    actual_micros: int,
    call_id: uuid.UUID | None,
) -> None:
    """Close the hold. Always runs — a cache hit settles to 0, and so does a failure;
    an unsettled reservation would keep a budget artificially full."""
    if not reservation.ids:
        return
    await session.execute(
        update(QuotaReservation)
        .where(QuotaReservation.id.in_(reservation.ids))
        .values(settled_micros=actual_micros, call_id=call_id)
    )
