"""In-process JobExecutor (ADR-0007 §1): claim → run → heartbeat/cancel → finalize.

The worker claims WHOLE jobs (never individual steps) with `FOR UPDATE SKIP LOCKED`,
commits `running` immediately (releasing the row lock), then runs each step's DuckDB
build through `run_engine` (thread offload) so the event loop stays free for the
concurrent heartbeat + cancel-poll coroutines. Post-claim concurrency is guarded by
`status` + `heartbeat_at`, not the row lock (a build runs for minutes).

The per-step version flip is atomic and idempotent: it deletes the target v<N+1> prefix
first (so a retry overwrites), writes parquet, then flips `current_version` in one
transaction that NO-OPS unless the job is still `running` and not cancel-requested — so a
requeued or cancelled job never double-writes a version (double S3 write + double flip is
exactly the failure the heartbeat/claim design prevents).
"""

import asyncio
import datetime
import logging
import uuid
from typing import Any

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from osaip_api.config import Settings
from osaip_api.events import publish_event
from osaip_api.job_logs import StepLogWriter, step_log_prefix
from osaip_api.models import Dataset, DatasetVersion, Job, JobStep, Project, Recipe
from osaip_api.propagation import apply_classification_floor
from osaip_api.recipe_execution import (
    make_snapshot_prefix,
    materialize_inputs,
    plan_inputs,
    resolve_inputs,
)
from osaip_api.secrets import Vault
from osaip_engine import duck
from osaip_engine import recipes as engine_recipes
from osaip_engine.aio import run_engine
from osaip_engine.errors import EngineError
from osaip_engine.storage import Storage
from osaip_shared.ids import new_id
from osaip_shared.storage_layout import dataset_version_location, dataset_version_prefix
from osaip_worker.sandbox import SandboxError, run_python_recipe

log = logging.getLogger("osaip.worker.executor")

HEARTBEAT_SECONDS = 5.0
CANCEL_POLL_SECONDS = 1.0
CLAIM_POLL_SECONDS = 2.0
SWEEP_INTERVAL_SECONDS = 30.0
REQUEUE_TIMEOUT_SECONDS = 60.0
MAX_ATTEMPTS = 3


class _Cancelled(Exception):
    """The job was cancel-requested; stop and mark it cancelled."""


class _Superseded(Exception):
    """The job is no longer 'running' (requeued/finalized elsewhere) — abandon quietly."""


class _PolicyBlocked(Exception):
    """A compliance policy blocked the step (e.g. Python recipe on BSN inputs)."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.public_message = message


_BLOCKED_CLASSIFICATIONS = {"bijzonder", "bsn"}


class _ConnHolder:
    """Shares the live build connection with the cancel-poll coroutine so it can
    interrupt an in-flight DuckDB query running in the offload thread."""

    def __init__(self) -> None:
        self.con: Any = None
        self.raw: Any = None
        self.interrupted = False


def _schema_json(columns: list[duck.Column]) -> dict[str, Any]:
    return {
        "columns": [
            {"name": col.name, "type": col.type, "nullable": col.nullable, "classification": "none"}
            for col in columns
        ]
    }


def _step_error(exc: BaseException) -> str:
    """Sanitized, user-safe step error (never a raw traceback/DSN — ADR-0007 §6)."""
    if isinstance(exc, EngineError | _PolicyBlocked):
        return exc.public_message
    if isinstance(exc, SandboxError):
        return exc.public_message
    from osaip_api.problem import Problem

    if isinstance(exc, Problem):
        return str(exc.detail)
    return "The build step failed."


def _blocking_labels(resolved: list[Any]) -> list[str]:
    """Special-category labels that block a Python recipe in v1 (ADR-0007 §5)."""
    found: set[str] = set()
    for item in resolved:
        dataset = item.dataset
        if dataset.classification in _BLOCKED_CLASSIFICATIONS:
            found.add(dataset.classification)
        if dataset.bbn_level == "bbn3":
            found.add("bbn3")
    return sorted(found)


def _run_python_build(
    storage: Storage,
    recipe_config: dict[str, Any],
    sources: list[Any],
    input_names: dict[int, str],
    dest_key: str,
    log_writer: "StepLogWriter",
) -> None:
    """Stage input parquet locally, run the sandbox, upload its output parquet. The
    sandbox has no S3/DB creds and no network — all IO is brokered here (ADR-0007 §5)."""
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory(prefix="osaip-pybuild-") as tmp:
        tmp_path = Path(tmp)
        local_inputs: dict[str, str] = {}
        for source in sources:
            key = source.s3_uri.split(f"{storage.config.bucket}/", 1)[1]
            local = tmp_path / f"in_{source.ordinal}.parquet"
            local.write_bytes(storage.get_bytes(key))
            local_inputs[input_names[source.ordinal]] = str(local)
        output_local = str(tmp_path / "out.parquet")
        result = run_python_recipe(
            recipe_config["code"],
            inputs=local_inputs,
            output_path=output_local,
            workdir=tmp,
        )
        if result.logs:
            log_writer.write(result.logs)
        storage.put_bytes(Path(output_local).read_bytes(), dest_key)


def _cleanup(con: Any, storage: Storage, snapshot_prefix: str) -> None:
    try:
        con.disconnect()
    except Exception:  # pragma: no cover - best-effort teardown
        log.exception("connection disconnect failed")
    try:
        storage.delete_prefix(f"{snapshot_prefix}/")
    except Exception:  # pragma: no cover
        log.exception("snapshot cleanup failed")


class JobExecutor:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        storage: Storage,
        vault: Vault,
        settings: Settings,
        worker_id: str,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._storage = storage
        self._vault = vault
        self._settings = settings
        self._worker_id = worker_id

    # ── Claim ────────────────────────────────────────────────────────────────────

    async def claim(self) -> uuid.UUID | None:
        """Atomically claim one queued job (FOR UPDATE SKIP LOCKED) and flip it to
        running. The row lock releases at commit; two concurrent claims never both win
        (the loser skips the locked row or sees it already running)."""
        async with self._sessionmaker() as session:
            row = (
                await session.execute(
                    text(
                        "SELECT id FROM jobs WHERE status = 'queued' "
                        "ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1"
                    )
                )
            ).first()
            if row is None:
                await session.rollback()
                return None
            raw_id = row[0]
            await session.execute(
                text(
                    "UPDATE jobs SET status = 'running', started_at = now(), "
                    "heartbeat_at = now(), claimed_by = :worker WHERE id = :id"
                ),
                {"worker": self._worker_id, "id": raw_id},
            )
            await session.commit()
            return uuid.UUID(str(raw_id))

    # ── Run a claimed job ────────────────────────────────────────────────────────

    async def execute_job(self, job_id: uuid.UUID) -> None:
        await run_engine(self._storage.ensure_bucket)
        async with self._sessionmaker() as session:
            job = (await session.execute(select(Job).where(Job.id == job_id))).scalar_one_or_none()
            if job is None or job.status != "running":
                return
            project = (
                await session.execute(select(Project).where(Project.id == job.project_id))
            ).scalar_one()
            steps = (
                (
                    await session.execute(
                        select(JobStep).where(JobStep.job_id == job_id).order_by(JobStep.ordinal)
                    )
                )
                .scalars()
                .all()
            )
            step_specs = [
                (step.id, step.ordinal, step.recipe_id, step.target_dataset_id, step.status)
                for step in steps
            ]
            project_id = project.id

        await self._emit(
            "jobs", "job.updated", project_id, {"id": str(job_id), "status": "running"}
        )

        stop = asyncio.Event()
        holder = _ConnHolder()
        heartbeat = asyncio.create_task(self._heartbeat_loop(job_id, stop))
        cancel = asyncio.create_task(self._cancel_loop(job_id, holder, stop))
        outcome: str | None = "succeeded"
        try:
            for step_id, ordinal, recipe_id, target_id, status in step_specs:
                if status != "queued":
                    continue
                if await self._cancel_requested(job_id):
                    outcome = "cancelled"
                    break
                try:
                    await self._run_step(
                        job_id, project, step_id, ordinal, recipe_id, target_id, holder
                    )
                except _Cancelled:
                    outcome = "cancelled"
                    break
                except _Superseded:
                    outcome = None  # a zombie run — do not touch the job
                    break
                except Exception as exc:  # genuine step failure
                    log.exception("build step failed")
                    await self._fail_step(step_id, exc)
                    outcome = "failed"
                    break
        finally:
            stop.set()
            await asyncio.gather(heartbeat, cancel, return_exceptions=True)

        if outcome is not None:
            await self._finalize_job(job_id, outcome, project_id)

    async def _run_step(
        self,
        job_id: uuid.UUID,
        project: Project,
        step_id: uuid.UUID,
        ordinal: int,
        recipe_id: uuid.UUID | None,
        target_id: uuid.UUID | None,
        holder: _ConnHolder,
    ) -> None:
        if recipe_id is None or target_id is None:  # recipe/dataset archived out from under us
            raise RuntimeError("Step is missing its recipe or target dataset.")
        storage = self._storage
        prefix = step_log_prefix(project.key, job_id, ordinal)
        log_writer = StepLogWriter(storage, prefix)
        await self._start_step(step_id, ordinal, prefix, project.id)

        # Async phase: resolve inputs + decrypt secrets. Everything blocking below is
        # offloaded via run_engine so the heartbeat/cancel coroutines keep running.
        async with self._sessionmaker() as session:
            recipe = (
                await session.execute(select(Recipe).where(Recipe.id == recipe_id))
            ).scalar_one()
            target = (
                await session.execute(select(Dataset).where(Dataset.id == target_id))
            ).scalar_one()
            resolved = await resolve_inputs(session, recipe_id)
            plans = await plan_inputs(session, self._vault, resolved)
            input_dataset_ids = [item.dataset.id for item in resolved]
            input_versions = {
                str(item.dataset.id): item.dataset.current_version for item in resolved
            }
            input_names = {item.ordinal: item.dataset.name for item in resolved}
            # CP compensating control (ADR-0007 §5): an un-isolated Python recipe must
            # not read special-category data until container isolation lands.
            if recipe.kind == "python":
                blocked = _blocking_labels(resolved)
                if blocked:
                    log_writer.write(f"Blocked: input(s) carry {', '.join(blocked)} labels.\n")
                    await run_engine(log_writer.flush)
                    raise _PolicyBlocked(
                        "Python recipes cannot read BSN / bijzonder / BBN-3 inputs in v1 "
                        "(no container isolation yet)."
                    )
            recipe_kind = recipe.kind
            recipe_config = dict(recipe.config)
            recipe_hash = recipe.config_hash
            target_name = target.name
            next_version = target.current_version + 1

        dest_prefix = dataset_version_prefix(project.key, target_name, next_version)
        dest_key = dataset_version_location(project.key, target_name, next_version)
        dest_uri = f"s3://{storage.config.bucket}/{dest_key}"
        snapshot_prefix = make_snapshot_prefix(project.key, f"job-{job_id}-step-{ordinal}")

        log_writer.write(f"Building {target_name} v{next_version} ({recipe_kind})\n")
        await run_engine(log_writer.flush)

        con = await run_engine(
            lambda: engine_recipes.open_connection(
                storage.config, memory_limit=self._settings.duckdb_build_memory_limit
            )
        )
        holder.con = con
        holder.raw = con.con
        try:
            if await self._cancel_requested(job_id):
                raise _Cancelled()

            def _do_build() -> tuple[list[duck.Column], int, dict[str, Any]]:
                # Idempotent overwrite: clear any partial artifact from a prior attempt.
                storage.delete_prefix(f"{dest_prefix}/")
                sources = materialize_inputs(storage, plans, snapshot_prefix, limit=None)
                if recipe_kind == "python":
                    _run_python_build(
                        storage, recipe_config, sources, input_names, dest_key, log_writer
                    )
                else:
                    if recipe_kind == "split":
                        # Only the primary output ('match') is built for now (ADR-0007 §5).
                        table, _rest = engine_recipes.compile_split(con, recipe_config, sources)
                    else:
                        table = engine_recipes.compile_recipe(
                            con, recipe_kind, recipe_config, sources
                        )
                    con.to_parquet(table, dest_uri)
                built_columns, built_rows = duck.validate_parquet(storage.config, dest_uri)
                built_profile = duck.profile_parquet(storage.config, dest_uri)
                return built_columns, built_rows, built_profile

            columns, row_count, profile = await run_engine(_do_build)
        except _Cancelled:
            raise
        except Exception as exc:
            # An interrupt (cancel) surfaces here as a DuckDB error — distinguish it from
            # a real failure by the cancel flag.
            if holder.interrupted or await self._cancel_requested(job_id):
                raise _Cancelled() from exc
            raise
        finally:
            holder.con = None
            holder.raw = None
            await run_engine(lambda: _cleanup(con, storage, snapshot_prefix))

        log_writer.write(f"Wrote {row_count} rows to v{next_version}\n")
        log_size = await run_engine(log_writer.flush)

        result = await self._commit_version(
            job_id=job_id,
            step_id=step_id,
            target_id=target_id,
            next_version=next_version,
            location=dest_uri,
            columns=columns,
            row_count=row_count,
            profile=profile,
            recipe_hash=recipe_hash,
            recipe_config=recipe_config,
            input_versions=input_versions,
            input_dataset_ids=input_dataset_ids,
            log_size=log_size,
        )
        if result == "cancelled":
            await self._skip_step(step_id)
            raise _Cancelled()
        if result == "superseded":
            raise _Superseded()
        await self._emit("datasets", "dataset.updated", project.id, {"name": target_name})
        await self._emit(
            "jobs",
            "step.updated",
            project.id,
            {"job_id": str(job_id), "ordinal": ordinal, "status": "succeeded"},
        )

    async def _commit_version(
        self,
        *,
        job_id: uuid.UUID,
        step_id: uuid.UUID,
        target_id: uuid.UUID,
        next_version: int,
        location: str,
        columns: list[duck.Column],
        row_count: int,
        profile: dict[str, Any],
        recipe_hash: str,
        recipe_config: dict[str, Any],
        input_versions: dict[str, int],
        input_dataset_ids: list[uuid.UUID],
        log_size: int,
    ) -> str:
        """The atomic flip. Serialized per-dataset by a pg advisory xact lock so two
        concurrent builds of D can't interleave, and no-ops unless the job is still
        running and un-cancelled. Returns 'flipped' | 'cancelled' | 'superseded'."""
        async with self._sessionmaker() as session:
            async with session.begin():
                await session.execute(
                    text("SELECT pg_advisory_xact_lock(hashtext('osaip_build:' || :d))"),
                    {"d": str(target_id)},
                )
                job = (
                    await session.execute(select(Job).where(Job.id == job_id).with_for_update())
                ).scalar_one()
                if job.status != "running":
                    return "superseded"
                if job.cancel_requested:
                    return "cancelled"
                target = (
                    await session.execute(
                        select(Dataset).where(Dataset.id == target_id).with_for_update()
                    )
                ).scalar_one()
                inputs = (
                    (
                        await session.execute(
                            select(Dataset).where(Dataset.id.in_(input_dataset_ids))
                        )
                    )
                    .scalars()
                    .all()
                    if input_dataset_ids
                    else []
                )
                session.add(
                    DatasetVersion(
                        id=new_id(),
                        dataset_id=target_id,
                        version=next_version,
                        location=location,
                        format="parquet",
                        schema_json=_schema_json(columns),
                        row_count=row_count,
                        row_count_kind="exact",
                        profile_json=profile,
                        recipe_config_hash=recipe_hash,
                        input_versions=input_versions,
                        config_snapshot=recipe_config,
                    )
                )
                target.current_version = next_version
                # CP-1 floor re-applied every build (ratchet); CP-2 purpose_codes stay as
                # declared at recipe save (ADR-0007 §7) — a manual override is preserved.
                apply_classification_floor(target, list(inputs))
                step = await session.get(JobStep, step_id)
                if step is not None:
                    step.status = "succeeded"
                    step.finished_at = datetime.datetime.now(datetime.UTC)
                    step.log_size = log_size
        return "flipped"

    # ── Step + job state helpers ─────────────────────────────────────────────────

    async def _start_step(
        self, step_id: uuid.UUID, ordinal: int, log_prefix: str, project_id: uuid.UUID
    ) -> None:
        async with self._sessionmaker() as session, session.begin():
            step = await session.get(JobStep, step_id)
            if step is not None:
                step.status = "running"
                step.started_at = datetime.datetime.now(datetime.UTC)
                step.log_prefix = log_prefix
        await self._emit(
            "jobs", "step.updated", project_id, {"ordinal": ordinal, "status": "running"}
        )

    async def _fail_step(self, step_id: uuid.UUID, exc: BaseException) -> None:
        async with self._sessionmaker() as session, session.begin():
            step = await session.get(JobStep, step_id)
            if step is not None:
                step.status = "failed"
                step.finished_at = datetime.datetime.now(datetime.UTC)
                step.error = _step_error(exc)[:2000]

    async def _skip_step(self, step_id: uuid.UUID) -> None:
        async with self._sessionmaker() as session, session.begin():
            step = await session.get(JobStep, step_id)
            if step is not None and step.status in ("queued", "running"):
                step.status = "skipped"
                step.finished_at = datetime.datetime.now(datetime.UTC)

    async def _cancel_requested(self, job_id: uuid.UUID) -> bool:
        async with self._sessionmaker() as session:
            value = (
                await session.execute(select(Job.cancel_requested).where(Job.id == job_id))
            ).scalar_one_or_none()
            return bool(value)

    async def _finalize_job(self, job_id: uuid.UUID, outcome: str, project_id: uuid.UUID) -> None:
        async with self._sessionmaker() as session:
            async with session.begin():
                job = (
                    await session.execute(select(Job).where(Job.id == job_id).with_for_update())
                ).scalar_one_or_none()
                if job is None or job.status != "running":
                    return  # already terminal (requeued/superseded)
                job.status = outcome
                job.finished_at = datetime.datetime.now(datetime.UTC)
                if outcome in ("failed", "cancelled"):
                    await session.execute(
                        update(JobStep)
                        .where(JobStep.job_id == job_id, JobStep.status.in_(("queued", "running")))
                        .values(status="skipped", finished_at=datetime.datetime.now(datetime.UTC))
                    )
        await self._emit("jobs", "job.updated", project_id, {"id": str(job_id), "status": outcome})

    async def _emit(
        self, topic: str, type_: str, project_id: uuid.UUID, payload: dict[str, Any]
    ) -> None:
        """Publish a low-frequency SSE event in its own short transaction (never holding
        the osaip_events advisory lock across the build — ADR-0007 §6)."""
        try:
            async with self._sessionmaker() as session, session.begin():
                await publish_event(
                    session, topic=topic, type=type_, project_id=project_id, payload=payload
                )
        except Exception:  # pragma: no cover - events are best-effort
            log.exception("event publish failed")

    # ── Concurrent coroutines ────────────────────────────────────────────────────

    async def _heartbeat_loop(self, job_id: uuid.UUID, stop: asyncio.Event) -> None:
        """Bump heartbeat_at while the (offloaded) step runs, so the sweeper never
        requeues a live build."""
        while not stop.is_set():
            try:
                async with self._sessionmaker() as session, session.begin():
                    await session.execute(
                        text(
                            "UPDATE jobs SET heartbeat_at = now() "
                            "WHERE id = :id AND status = 'running'"
                        ),
                        {"id": str(job_id)},
                    )
            except Exception:  # pragma: no cover
                log.exception("heartbeat update failed")
            if await _wait(stop, HEARTBEAT_SECONDS):
                return

    async def _cancel_loop(
        self, job_id: uuid.UUID, holder: _ConnHolder, stop: asyncio.Event
    ) -> None:
        """Poll cancel_requested; on cancel, interrupt the live step connection so a
        long-running COPY stops (between-steps checks alone can't stop a long step)."""
        while not stop.is_set():
            if await _wait(stop, CANCEL_POLL_SECONDS):
                return
            try:
                if await self._cancel_requested(job_id):
                    holder.interrupted = True
                    raw = holder.raw
                    if raw is not None:
                        try:
                            raw.interrupt()
                        except Exception:  # pragma: no cover
                            log.exception("connection interrupt failed")
                    return
            except Exception:  # pragma: no cover
                log.exception("cancel poll failed")

    # ── Requeue sweeper (poison-job capped) ──────────────────────────────────────

    async def sweep(self) -> None:
        """Requeue jobs whose worker died (stale heartbeat); cap retries so a poison job
        can't loop forever (ADR-0007 §1). FOR UPDATE SKIP LOCKED avoids racing a live
        worker's finalize on the same row."""
        async with self._sessionmaker() as session, session.begin():
            stale = (
                await session.execute(
                    text(
                        "SELECT id, attempts FROM jobs WHERE status = 'running' "
                        "AND heartbeat_at < now() - make_interval(secs => :timeout) "
                        "FOR UPDATE SKIP LOCKED"
                    ),
                    {"timeout": REQUEUE_TIMEOUT_SECONDS},
                )
            ).all()
            for stale_id, attempts in stale:
                if attempts + 1 > MAX_ATTEMPTS:
                    await session.execute(
                        text(
                            "UPDATE jobs SET status = 'failed', attempts = attempts + 1, "
                            "finished_at = now(), claimed_by = NULL WHERE id = :id"
                        ),
                        {"id": stale_id},
                    )
                    await session.execute(
                        text(
                            "UPDATE job_steps SET status = 'skipped', finished_at = now() "
                            "WHERE job_id = :id AND status IN ('queued', 'running')"
                        ),
                        {"id": stale_id},
                    )
                else:
                    await session.execute(
                        text(
                            "UPDATE jobs SET status = 'queued', attempts = attempts + 1, "
                            "claimed_by = NULL, heartbeat_at = NULL, started_at = NULL "
                            "WHERE id = :id"
                        ),
                        {"id": stale_id},
                    )
                    # Reset the interrupted step so re-execution redoes it (the build write
                    # is idempotent — it deletes v<N+1> before rewriting).
                    await session.execute(
                        text(
                            "UPDATE job_steps SET status = 'queued', started_at = NULL "
                            "WHERE job_id = :id AND status = 'running'"
                        ),
                        {"id": stale_id},
                    )

    # ── Orphan version sweeper ───────────────────────────────────────────────────

    async def prune_orphans(self) -> int:
        """Delete parquet under v<N> prefixes with N > current_version and no
        dataset_versions row — leftovers from a crashed build (mirror _prune_uploads_sync).
        """
        async with self._sessionmaker() as session:
            datasets = (
                await session.execute(
                    select(Project.key, Dataset.id, Dataset.name, Dataset.current_version).join(
                        Project, Project.id == Dataset.project_id
                    )
                )
            ).all()
            versions = (
                await session.execute(select(DatasetVersion.dataset_id, DatasetVersion.version))
            ).all()
        committed: dict[Any, set[int]] = {}
        for dataset_id, version in versions:
            committed.setdefault(dataset_id, set()).add(version)
        specs = [
            (key, name, current, committed.get(dataset_id, set()))
            for key, dataset_id, name, current in datasets
        ]
        return await run_engine(lambda: _prune_orphans_sync(self._storage, specs))


def _prune_orphans_sync(storage: Storage, specs: list[tuple[str, str, int, set[int]]]) -> int:
    removed = 0
    for key, name, current, committed in specs:
        prefix = f"projects/{key}/datasets/{name}/"
        present: set[int] = set()
        for object_key, _ in storage.list_keys(prefix):
            first = object_key[len(prefix) :].split("/", 1)[0]
            if first.startswith("v") and first[1:].isdigit():
                present.add(int(first[1:]))
        for version in present:
            if version > current and version not in committed:
                removed += storage.delete_prefix(f"{prefix}v{version}/")
    return removed


async def _wait(stop: asyncio.Event, seconds: float) -> bool:
    """Sleep up to `seconds`, waking early if `stop` is set. True ⇒ stopped."""
    try:
        await asyncio.wait_for(stop.wait(), timeout=seconds)
        return True
    except TimeoutError:
        return False


# ── Loops wired into the worker (main.py) ────────────────────────────────────────


async def job_loop(executor: JobExecutor, poll: float = CLAIM_POLL_SECONDS) -> None:
    while True:
        job_id: uuid.UUID | None = None
        try:
            job_id = await executor.claim()
        except Exception:
            log.exception("claim failed")
        if job_id is None:
            await asyncio.sleep(poll)
            continue
        try:
            await executor.execute_job(job_id)
        except Exception:  # pragma: no cover - execute_job contains its own guards
            log.exception("job execution crashed")


async def sweep_loop(executor: JobExecutor, interval: float = SWEEP_INTERVAL_SECONDS) -> None:
    while True:
        try:
            await executor.sweep()
        except Exception:
            log.exception("sweep failed")
        await asyncio.sleep(interval)
