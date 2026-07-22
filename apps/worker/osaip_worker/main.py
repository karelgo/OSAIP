"""Worker entrypoint.

Phase 0 scope: heartbeat + housekeeping (event retention per ADR-0003, idempotency-key
pruning). The Postgres-backed job queue (FOR UPDATE SKIP LOCKED) is Phase 2 (spec §3.2).
"""

import asyncio
import logging
import os

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

log = logging.getLogger("osaip.worker")

HEARTBEAT_SECONDS = 30
PRUNE_INTERVAL_SECONDS = 600
EVENT_RETENTION_DAYS = 7
IDEMPOTENCY_RETENTION_HOURS = 24


async def heartbeat(engine: AsyncEngine) -> None:
    while True:
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            log.info("heartbeat ok")
        except Exception:
            log.exception("heartbeat failed")
        await asyncio.sleep(HEARTBEAT_SECONDS)


async def prune(engine: AsyncEngine) -> None:
    while True:
        try:
            async with engine.begin() as conn:
                events = await conn.execute(
                    text("DELETE FROM events WHERE ts < now() - make_interval(days => :days)"),
                    {"days": EVENT_RETENTION_DAYS},
                )
                keys = await conn.execute(
                    text(
                        "DELETE FROM idempotency_keys "
                        "WHERE created_at < now() - make_interval(hours => :hours)"
                    ),
                    {"hours": IDEMPOTENCY_RETENTION_HOURS},
                )
            log.info("prune ok: %s events, %s idempotency keys", events.rowcount, keys.rowcount)
        except Exception:
            log.exception("prune failed")
        await asyncio.sleep(PRUNE_INTERVAL_SECONDS)


async def run() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    database_url = os.environ.get(
        "OSAIP_DATABASE_URL", "postgresql+asyncpg://osaip:osaip@localhost:5433/osaip"
    )
    engine = create_async_engine(database_url)
    await asyncio.gather(heartbeat(engine), prune(engine))


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
