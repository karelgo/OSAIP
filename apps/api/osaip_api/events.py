"""SSE event bus internals (ADR-0003).

Publishing inserts an `events` row under a short advisory lock (seq order == commit
order) and fires an EMPTY pg_notify as a pure wake-up. Each api process holds ONE
dedicated LISTEN connection; subscribers get an asyncio.Event flag and read the table
themselves with their own cursor — one code path for live tail and replay.
"""

import asyncio
import contextlib
import logging
import uuid
from typing import Any

import asyncpg
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from osaip_api.models import Event

log = logging.getLogger("osaip.events")

CHANNEL = "osaip_events"
_EVENTS_LOCK_SQL = text("SELECT pg_advisory_xact_lock(hashtext('osaip_events'))")


async def publish_event(
    session: AsyncSession,
    *,
    topic: str,
    type: str,
    project_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    payload: dict[str, Any] | None = None,
) -> Event:
    """Insert an event inside the caller's transaction. NOTIFY fires at COMMIT, so
    subscribers only ever wake for committed rows."""
    await session.execute(_EVENTS_LOCK_SQL)
    event = Event(
        topic=topic, type=type, project_id=project_id, user_id=user_id, payload=payload or {}
    )
    session.add(event)
    await session.flush()
    await session.execute(text(f"SELECT pg_notify('{CHANNEL}', '')"))
    return event


def asyncpg_dsn(sqlalchemy_url: str) -> str:
    return sqlalchemy_url.replace("postgresql+asyncpg://", "postgresql://", 1)


class EventBroker:
    """One per process: a dedicated (non-pooled) LISTEN connection fanning a bare
    wake-up flag to every subscriber. Reconnects with backoff if the connection dies."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._conn: Any = None
        self._task: asyncio.Task[None] | None = None
        self._waiters: set[asyncio.Event] = set()
        self._stopped = False
        self._closing = asyncio.Event()

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        backoff = 1.0
        while not self._stopped:
            try:
                self._conn = await asyncpg.connect(self._dsn)
                await self._conn.add_listener(CHANNEL, self._on_notify)
                backoff = 1.0
                await self._closing.wait()
            except asyncio.CancelledError:
                return
            except Exception:
                log.exception("event LISTEN connection lost; reconnecting")
                # Wake subscribers so nobody sleeps through events missed while down.
                self._wake_all()
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)
            finally:
                if self._conn is not None:
                    with contextlib.suppress(Exception):
                        await self._conn.close()
                    self._conn = None

    def _on_notify(self, *args: Any) -> None:
        self._wake_all()

    def _wake_all(self) -> None:
        for waiter in self._waiters:
            waiter.set()

    def subscribe(self) -> asyncio.Event:
        waiter = asyncio.Event()
        self._waiters.add(waiter)
        return waiter

    def unsubscribe(self, waiter: asyncio.Event) -> None:
        self._waiters.discard(waiter)

    async def stop(self) -> None:
        self._stopped = True
        self._closing.set()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task


async def fetch_events_after(
    session: AsyncSession, cursor: int, *, limit: int = 500
) -> list[Event]:
    return list(
        (
            await session.execute(
                select(Event).where(Event.seq > cursor).order_by(Event.seq).limit(limit)
            )
        )
        .scalars()
        .all()
    )


async def current_head(session: AsyncSession) -> int:
    result = (await session.execute(text("SELECT coalesce(max(seq), 0) FROM events"))).scalar_one()
    return int(result)


async def min_available_seq(session: AsyncSession) -> int | None:
    result = (await session.execute(text("SELECT min(seq) FROM events"))).scalar_one()
    return int(result) if result is not None else None
