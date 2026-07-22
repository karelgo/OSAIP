"""Worker entrypoint.

Phase 0 scope: prove the process boots against the database and stays alive
(heartbeat log). The event-prune job joins with the SSE slice; the Postgres-backed
job queue (FOR UPDATE SKIP LOCKED) is Phase 2 (spec §3.2).
"""

import asyncio
import logging
import os

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

log = logging.getLogger("osaip.worker")

HEARTBEAT_SECONDS = 30


async def run() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    database_url = os.environ.get(
        "OSAIP_DATABASE_URL", "postgresql+asyncpg://osaip:osaip@localhost:5433/osaip"
    )
    engine = create_async_engine(database_url)
    while True:
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            log.info("heartbeat ok")
        except Exception:  # noqa: BLE001 — keep the loop alive, report, retry
            log.exception("heartbeat failed")
        await asyncio.sleep(HEARTBEAT_SECONDS)


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
