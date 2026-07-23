"""JobExecutor: SKIP-LOCKED no-double-claim, heartbeat requeue, a real end-to-end
build (upload → prepare recipe → executor → versioned output), step failure, and the
atomic no-op when a job is cancelled mid-flight.

Runs against the same testcontainer DB + SeaweedFS as the API tests; the executor is
built from the app's own state (sessionmaker/storage/vault/settings)."""

import asyncio
import datetime
import uuid
from collections.abc import Awaitable, Callable

import httpx
from fastapi import FastAPI
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from osaip_api.config import Settings
from osaip_api.models import Dataset, DatasetVersion, Job, JobStep, Project
from osaip_worker.executor import JobExecutor

LoginAs = Callable[..., Awaitable[httpx.AsyncClient]]

CSV = b"order_id,amount,region\n1,10.0,NL\n2,20.0,BE\n3,30.0,NL\n"


def _executor(app: FastAPI, settings: Settings, worker_id: str = "w1") -> JobExecutor:
    return JobExecutor(
        app.state.sessionmaker, app.state.storage, app.state.vault, settings, worker_id
    )


async def _upload_dataset(client: httpx.AsyncClient, key: str, name: str) -> None:
    assert (
        await client.post("/api/v1/projects", json={"key": key, "name": key})
    ).status_code == 201
    up = await client.post(
        f"/api/v1/projects/{key}/uploads", files={"file": ("o.csv", CSV, "text/csv")}
    )
    created = await client.post(
        f"/api/v1/projects/{key}/datasets",
        json={
            "name": name,
            "source": {"kind": "upload", "upload_id": up.json()["upload_id"]},
            "legal_basis": "demo",
            "purpose_codes": ["demo"],
        },
    )
    assert created.status_code == 201, created.text


async def _dataset(db: AsyncSession, project_key: str, name: str) -> Dataset:
    return (
        await db.execute(
            select(Dataset)
            .join(Project, Project.id == Dataset.project_id)
            .where(Dataset.name == name, Project.key == project_key)
        )
    ).scalar_one()


async def _run_build(app: FastAPI, settings: Settings, db: AsyncSession, job_id: str) -> None:
    """Run a SPECIFIC job (claim() is global FIFO and other tests leave queued jobs, so
    tests that assert on their own output run their own job id). Mark it running — what
    claim() does atomically — then execute it."""
    await db.execute(
        text("UPDATE jobs SET status='running', started_at=now(), heartbeat_at=now() WHERE id=:id"),
        {"id": job_id},
    )
    await db.commit()
    await _executor(app, settings).execute_job(uuid.UUID(job_id))


async def test_no_double_claim(
    duck_extensions: None,
    app: FastAPI,
    settings: Settings,
    login_as: LoginAs,
    db_session: AsyncSession,
) -> None:
    admin = await login_as("ex-admin", "ex-admin@osaip.dev")
    await _upload_dataset(admin, "exq", "orders")
    await admin.post(
        "/api/v1/projects/exq/recipes",
        json={
            "name": "clean",
            "kind": "prepare",
            "config": {"steps": [{"op": "dedupe", "subset": ["order_id"]}]},
            "input_dataset_names": ["orders"],
            "output_names": ["clean_out"],
        },
    )
    await admin.post("/api/v1/projects/exq/builds", json={"targets": ["clean_out"]})

    # Two executors race — SKIP LOCKED guarantees they never claim the SAME job (other
    # tests may leave queued jobs in the shared DB, so we assert distinctness, not that
    # exactly one wins globally).
    a, b = _executor(app, settings, "wa"), _executor(app, settings, "wb")
    first, second = await asyncio.gather(a.claim(), b.claim())
    assert first != second or (first is None and second is None)
    if first is not None and second is not None:
        assert first != second


async def test_full_build_end_to_end(
    duck_extensions: None,
    app: FastAPI,
    settings: Settings,
    login_as: LoginAs,
    db_session: AsyncSession,
) -> None:
    admin = await login_as("ex-admin2", "ex-admin2@osaip.dev")
    await _upload_dataset(admin, "exb", "orders")
    await admin.post(
        "/api/v1/projects/exb/recipes",
        json={
            "name": "nl_only",
            "kind": "prepare",
            "config": {"steps": [{"op": "filter", "expression": 'col("region") == "NL"'}]},
            "input_dataset_names": ["orders"],
            "output_names": ["nl_orders"],
        },
    )
    job = (await admin.post("/api/v1/projects/exb/builds", json={"targets": ["nl_orders"]})).json()
    await _run_build(app, settings, db_session, job["id"])
    job_id = uuid.UUID(job["id"])

    # the output dataset is now built at v1, with a profile, and the sample reads NL only
    dataset = await _dataset(db_session, "exb", "nl_orders")
    await db_session.refresh(dataset)
    assert dataset.current_version == 1
    version = (
        await db_session.execute(
            select(DatasetVersion).where(
                DatasetVersion.dataset_id == dataset.id, DatasetVersion.version == 1
            )
        )
    ).scalar_one()
    assert version.row_count == 2  # only the two NL rows
    assert version.profile_json is not None
    assert version.recipe_config_hash is not None

    job = (await db_session.execute(select(Job).where(Job.id == job_id))).scalar_one()
    await db_session.refresh(job)
    assert job.status == "succeeded"

    sample = await admin.get("/api/v1/projects/exb/datasets/nl_orders/sample")
    assert sample.status_code == 200
    assert {r["region"] for r in sample.json()["rows"]} == {"NL"}


async def test_step_failure_fails_job(
    duck_extensions: None,
    app: FastAPI,
    settings: Settings,
    login_as: LoginAs,
    db_session: AsyncSession,
) -> None:
    admin = await login_as("ex-admin3", "ex-admin3@osaip.dev")
    await _upload_dataset(admin, "exf", "orders")
    # a formula referencing a non-existent column → compile error at build
    await admin.post(
        "/api/v1/projects/exf/recipes",
        json={
            "name": "bad",
            "kind": "prepare",
            "config": {"steps": [{"op": "formula", "column": "x", "expression": 'col("nope")'}]},
            "input_dataset_names": ["orders"],
            "output_names": ["bad_out"],
        },
    )
    job = (await admin.post("/api/v1/projects/exf/builds", json={"targets": ["bad_out"]})).json()
    await _run_build(app, settings, db_session, job["id"])
    job_id = uuid.UUID(job["id"])

    job = (await db_session.execute(select(Job).where(Job.id == job_id))).scalar_one()
    await db_session.refresh(job)
    assert job.status == "failed"
    step = (await db_session.execute(select(JobStep).where(JobStep.job_id == job_id))).scalar_one()
    assert step.status == "failed" and step.error
    # the output was never built
    out = await _dataset(db_session, "exf", "bad_out")
    await db_session.refresh(out)
    assert out.current_version == 0


async def test_requeue_after_heartbeat_timeout(
    app: FastAPI, settings: Settings, db_session: AsyncSession
) -> None:
    # a running job with a stale heartbeat → sweeper requeues it (attempts++)
    from osaip_api.models import Project

    project = Project(key="exsweep", name="exsweep", storage_prefix="projects/exsweep")
    db_session.add(project)
    await db_session.flush()
    stale = datetime.datetime.now(datetime.UTC) - datetime.timedelta(seconds=120)
    job = Job(
        project_id=project.id,
        status="running",
        trigger="manual",
        heartbeat_at=stale,
        attempts=0,
    )
    db_session.add(job)
    await db_session.commit()

    executor = _executor(app, settings)
    await executor.sweep()
    await db_session.refresh(job)
    assert job.status == "queued" and job.attempts == 1

    # exhaust attempts → failed (poison-job cap)
    await db_session.execute(
        text(
            "UPDATE jobs SET status='running', attempts=3, "
            "heartbeat_at=now() - interval '120 seconds' WHERE id=:id"
        ),
        {"id": str(job.id)},
    )
    await db_session.commit()
    await executor.sweep()
    await db_session.refresh(job)
    assert job.status == "failed"


async def test_cancelled_job_does_not_build(
    duck_extensions: None,
    app: FastAPI,
    settings: Settings,
    login_as: LoginAs,
    db_session: AsyncSession,
) -> None:
    admin = await login_as("ex-admin4", "ex-admin4@osaip.dev")
    await _upload_dataset(admin, "exc", "orders")
    await admin.post(
        "/api/v1/projects/exc/recipes",
        json={
            "name": "cxl",
            "kind": "prepare",
            "config": {"steps": [{"op": "dedupe", "subset": []}]},
            "input_dataset_names": ["orders"],
            "output_names": ["cxl_out"],
        },
    )
    job = (await admin.post("/api/v1/projects/exc/builds", json={"targets": ["cxl_out"]})).json()
    # cancel a still-queued job → cancelled outright, steps skipped
    await admin.post(f"/api/v1/projects/exc/jobs/{job['id']}/cancel")

    # This job is no longer claimable (status=cancelled, not queued); even if the
    # executor were handed its id, execute_job no-ops on a non-running job.
    executor = _executor(app, settings)
    await executor.execute_job(uuid.UUID(job["id"]))

    fetched = (
        await db_session.execute(select(Job).where(Job.id == uuid.UUID(job["id"])))
    ).scalar_one()
    await db_session.refresh(fetched)
    assert fetched.status == "cancelled"
    out = await _dataset(db_session, "exc", "cxl_out")
    await db_session.refresh(out)
    assert out.current_version == 0  # never built


async def test_python_recipe_build_and_bsn_gate(
    duck_extensions: None,
    app: FastAPI,
    settings: Settings,
    login_as: LoginAs,
    db_session: AsyncSession,
) -> None:
    admin = await login_as("ex-admin5", "ex-admin5@osaip.dev")
    await _upload_dataset(admin, "expy", "orders")
    code = (
        "import osaip\n"
        "import pyarrow.parquet as pq\n"
        "t = pq.read_table(osaip.input('orders'))\n"
        "pq.write_table(t.slice(0, 1), osaip.output())\n"
    )
    await admin.post(
        "/api/v1/projects/expy/recipes",
        json={
            "name": "pyr",
            "kind": "python",
            "config": {"code": code},
            "input_dataset_names": ["orders"],
            "output_names": ["py_out"],
        },
    )
    job = (await admin.post("/api/v1/projects/expy/builds", json={"targets": ["py_out"]})).json()
    await _run_build(app, settings, db_session, job["id"])
    out = await _dataset(db_session, "expy", "py_out")
    await db_session.refresh(out)
    assert out.current_version == 1  # sandboxed python build produced v1

    # Now label the input BSN and rebuild-force → the compensating gate blocks it.
    await admin.patch("/api/v1/projects/expy/datasets/orders", json={"classification": "bsn"})
    job2 = (
        await admin.post(
            "/api/v1/projects/expy/builds", json={"targets": ["py_out"], "force": True}
        )
    ).json()
    await _run_build(app, settings, db_session, job2["id"])
    job_id2 = uuid.UUID(job2["id"])
    job = (await db_session.execute(select(Job).where(Job.id == job_id2))).scalar_one()
    await db_session.refresh(job)
    assert job.status == "failed"
    step = (await db_session.execute(select(JobStep).where(JobStep.job_id == job_id2))).scalar_one()
    assert "BSN" in (step.error or "")
