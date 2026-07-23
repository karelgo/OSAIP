"""Worker entrypoint.

Housekeeping: heartbeat, event retention (ADR-0003), idempotency-key pruning, and
raw-upload pruning (Phase 1 plan §3: uploads are transient, >24h are deleted). Phase 2
(ADR-0007 §1) adds the Postgres-backed job queue: a claim/run loop (FOR UPDATE SKIP
LOCKED), a requeue sweeper, and an orphan-version sweeper, all via `JobExecutor`.
"""

import asyncio
import datetime
import logging
import os
import socket

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from osaip_api.config import get_settings
from osaip_api.db import make_sessionmaker
from osaip_api.secrets import Vault
from osaip_engine.storage import Storage, StorageConfig
from osaip_worker.executor import JobExecutor, job_loop, sweep_loop

log = logging.getLogger("osaip.worker")

HEARTBEAT_SECONDS = 30
PRUNE_INTERVAL_SECONDS = 600
EVENT_RETENTION_DAYS = 7
IDEMPOTENCY_RETENTION_HOURS = 24
UPLOAD_RETENTION_HOURS = 24


def _storage_from_env() -> Storage:
    return Storage(
        StorageConfig(
            endpoint=os.environ.get("OSAIP_S3_ENDPOINT", "localhost:8333"),
            bucket=os.environ.get("OSAIP_S3_BUCKET", "osaip"),
            access_key=os.environ.get("OSAIP_S3_ACCESS_KEY", "osaipdev"),
            secret_key=os.environ.get("OSAIP_S3_SECRET_KEY", "osaip-dev-s3-secret"),
            region=os.environ.get("OSAIP_S3_REGION", "us-east-1"),
            use_ssl=os.environ.get("OSAIP_S3_USE_SSL", "0") in {"1", "true"},
        )
    )


def _prune_uploads_sync(storage: Storage) -> int:
    """Delete raw uploads older than the retention window (blocking boto3 — runs in
    a thread). Uploads live at projects/<key>/uploads/<upload_id>/..."""
    cutoff = datetime.datetime.now(datetime.UTC) - datetime.timedelta(hours=UPLOAD_RETENTION_HOURS)
    stale_prefixes: set[str] = set()
    for key, last_modified in storage.list_keys("projects/"):
        parts = key.split("/")
        if len(parts) >= 4 and parts[2] == "uploads" and last_modified < cutoff:
            stale_prefixes.add("/".join(parts[:4]))
    removed = 0
    for prefix in stale_prefixes:
        removed += storage.delete_prefix(prefix)
    return removed


async def heartbeat(engine: AsyncEngine) -> None:
    while True:
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            log.info("heartbeat ok")
        except Exception:
            log.exception("heartbeat failed")
        await asyncio.sleep(HEARTBEAT_SECONDS)


async def prune(engine: AsyncEngine, executor: "JobExecutor") -> None:
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
        try:
            storage = _storage_from_env()
            removed = await asyncio.to_thread(_prune_uploads_sync, storage)
            if removed:
                log.info("upload prune ok: %s objects removed", removed)
        except Exception:
            log.exception("upload prune failed")
        try:
            orphans = await executor.prune_orphans()
            if orphans:
                log.info("orphan version prune ok: %s objects removed", orphans)
        except Exception:
            log.exception("orphan prune failed")
        await asyncio.sleep(PRUNE_INTERVAL_SECONDS)


def _worker_id() -> str:
    return os.environ.get("OSAIP_WORKER_ID") or f"{socket.gethostname()}:{os.getpid()}"


async def run() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    executor = JobExecutor(
        make_sessionmaker(engine),
        _storage_from_env(),
        Vault(settings.secret_key),
        settings,
        _worker_id(),
    )
    await asyncio.gather(
        heartbeat(engine),
        prune(engine, executor),
        job_loop(executor),
        sweep_loop(executor),
    )


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
