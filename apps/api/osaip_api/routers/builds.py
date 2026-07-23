"""Builds & jobs (ADR-0007 §1/§6, spec §3.2). `POST /builds` resolves the target
datasets to a topologically ordered set of recipe steps and enqueues one job the worker
claims (FOR UPDATE SKIP LOCKED). Jobs are read back with their step timeline; step logs
tail from S3 chunk objects by byte offset.

Mutation ordering (ADR-0005): mutate → publish_event → write_audit LAST → commit.
"""

import base64
import datetime
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import literal, select, tuple_, update
from sqlalchemy.ext.asyncio import AsyncSession

from osaip_api.audit import write_audit
from osaip_api.auth.deps import CurrentUser
from osaip_api.build_service import resolve_build
from osaip_api.db import get_session
from osaip_api.events import publish_event
from osaip_api.idempotency import check_idempotency, store_idempotent_response
from osaip_api.job_logs import read_step_log, step_log_prefix
from osaip_api.models import Dataset, Job, JobStep, Recipe
from osaip_api.permissions import ProjectContext, load_project_context
from osaip_api.problem import Problem
from osaip_api.schemas import JobListOut, JobOut, LogTailOut
from osaip_engine.aio import run_engine
from osaip_engine.storage import Storage
from osaip_shared.ids import new_id

router = APIRouter(prefix="/projects/{key}", tags=["builds"])

DbSession = Annotated[AsyncSession, Depends(get_session)]

_ACTIVE = ("queued", "running")


class BuildCreate(BaseModel):
    targets: list[str] = Field(min_length=1, max_length=64)
    force: bool = False


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _encode_cursor(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode()).decode()


def _decode_cursor(cursor: str) -> str:
    try:
        return base64.urlsafe_b64decode(cursor.encode()).decode()
    except Exception as exc:
        raise Problem(
            400,
            title="Invalid cursor",
            detail="The pagination cursor is not valid.",
            hint="Restart from the first page (omit `cursor`).",
            slug="invalid-cursor",
        ) from exc


def _iso(value: datetime.datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


async def _steps_payload(session: AsyncSession, job_id: uuid.UUID) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            select(JobStep, Recipe.name, Dataset.name)
            .outerjoin(Recipe, Recipe.id == JobStep.recipe_id)
            .outerjoin(Dataset, Dataset.id == JobStep.target_dataset_id)
            .where(JobStep.job_id == job_id)
            .order_by(JobStep.ordinal)
        )
    ).all()
    return [
        {
            "ordinal": step.ordinal,
            "recipe_name": recipe_name,
            "target_dataset_name": dataset_name,
            "status": step.status,
            "error": step.error,
            "log_size": step.log_size,
            "started_at": _iso(step.started_at),
            "finished_at": _iso(step.finished_at),
        }
        for step, recipe_name, dataset_name in rows
    ]


async def _job_payload(session: AsyncSession, job: Job) -> dict[str, Any]:
    return {
        "id": str(job.id),
        "kind": job.kind,
        "status": job.status,
        "trigger": job.trigger,
        "attempts": job.attempts,
        "created_at": job.created_at.isoformat(),
        "started_at": _iso(job.started_at),
        "finished_at": _iso(job.finished_at),
        "steps": await _steps_payload(session, job.id),
    }


async def _get_job(session: AsyncSession, ctx: ProjectContext, job_id: str) -> Job:
    try:
        parsed = uuid.UUID(job_id)
    except ValueError as exc:
        raise Problem(
            404,
            title="Job not found",
            detail="No such job in this project.",
            hint="Check the job id.",
            slug="not-found",
        ) from exc
    job = (
        await session.execute(select(Job).where(Job.id == parsed, Job.project_id == ctx.project.id))
    ).scalar_one_or_none()
    if job is None:
        raise Problem(
            404,
            title="Job not found",
            detail="No such job in this project.",
            hint="Check the job id.",
            slug="not-found",
        )
    return job


# ── Create a build ───────────────────────────────────────────────────────────────


@router.post("/builds", response_model=JobOut)
async def create_build(
    key: str, body: BuildCreate, request: Request, user: CurrentUser, session: DbSession
) -> JSONResponse:
    ctx = await load_project_context(session, user, key, min_role="editor")
    idem_key, req_hash, stored = await check_idempotency(session, request, user, body.model_dump())
    if stored is not None:
        return JSONResponse(content=stored[1], status_code=stored[0])

    # Coalesce: if any requested target already has a queued/running step, return that
    # job rather than enqueue a duplicate build of the same dataset (ADR-0007 §1).
    existing = (
        (
            await session.execute(
                select(Job)
                .join(JobStep, JobStep.job_id == Job.id)
                .join(Dataset, Dataset.id == JobStep.target_dataset_id)
                .where(
                    Job.project_id == ctx.project.id,
                    Job.status.in_(_ACTIVE),
                    Dataset.name.in_(body.targets),
                )
                .order_by(Job.created_at.desc())
                .limit(1)
            )
        )
        .scalars()
        .first()
    )
    if existing is not None:
        payload = await _job_payload(session, existing)
        if idem_key is not None:
            await store_idempotent_response(
                session, user, idem_key, request, req_hash, 200, payload
            )
            await session.commit()
        return JSONResponse(content=payload, status_code=200)

    steps = await resolve_build(session, ctx.project, body.targets, body.force)

    now = datetime.datetime.now(datetime.UTC)
    if steps:
        job = Job(
            id=new_id(),
            project_id=ctx.project.id,
            kind="build",
            status="queued",
            trigger="manual",
            requested_by=user.id,
        )
    else:
        # Nothing to build (everything fresh, not forced): record a 0-step job that is
        # already succeeded, so the API contract is uniform (POST /builds → JobOut) and
        # the run drawer can still deep-link to it.
        job = Job(
            id=new_id(),
            project_id=ctx.project.id,
            kind="build",
            status="succeeded",
            trigger="manual",
            requested_by=user.id,
            started_at=now,
            finished_at=now,
        )
    session.add(job)
    await session.flush()
    for step in steps:
        session.add(
            JobStep(
                id=new_id(),
                job_id=job.id,
                ordinal=step.ordinal,
                recipe_id=step.recipe_id,
                target_dataset_id=step.target_dataset_id,
                status="queued",
            )
        )
    await session.flush()

    await publish_event(
        session,
        topic="jobs",
        type="job.created",
        project_id=ctx.project.id,
        payload={"id": str(job.id), "status": job.status},
    )
    await write_audit(
        session,
        actor_id=user.id,
        project_id=ctx.project.id,
        action="build.requested",
        object_kind="job",
        object_id=str(job.id),
        details={"targets": body.targets, "force": body.force, "steps": len(steps)},
        ip=_client_ip(request),
    )
    payload = await _job_payload(session, job)
    if idem_key is not None:
        await store_idempotent_response(session, user, idem_key, request, req_hash, 200, payload)
    await session.commit()
    return JSONResponse(content=payload, status_code=200)


# ── Read jobs ────────────────────────────────────────────────────────────────────


@router.get("/jobs", response_model=JobListOut)
async def list_jobs(
    key: str,
    user: CurrentUser,
    session: DbSession,
    status: str | None = None,
    limit: int = 50,
    cursor: str | None = None,
) -> dict[str, Any]:
    ctx = await load_project_context(session, user, key, min_role="viewer")
    limit = max(1, min(limit, 200))
    query = select(Job).where(Job.project_id == ctx.project.id)
    if status is not None:
        query = query.where(Job.status == status)
    query = query.order_by(Job.created_at.desc(), Job.id.desc()).limit(limit + 1)
    if cursor:
        created_raw, id_raw = _decode_cursor(cursor).split("|", 1)
        query = query.where(
            tuple_(Job.created_at, Job.id)
            < tuple_(
                literal(datetime.datetime.fromisoformat(created_raw)), literal(uuid.UUID(id_raw))
            )
        )
    jobs = (await session.execute(query)).scalars().all()
    has_more = len(jobs) > limit
    jobs = jobs[:limit]
    items = [await _job_payload(session, job) for job in jobs]
    next_cursor = (
        _encode_cursor(f"{jobs[-1].created_at.isoformat()}|{jobs[-1].id}")
        if has_more and jobs
        else None
    )
    return {"items": items, "next_cursor": next_cursor}


@router.get("/jobs/{job_id}", response_model=JobOut)
async def get_job(key: str, job_id: str, user: CurrentUser, session: DbSession) -> dict[str, Any]:
    ctx = await load_project_context(session, user, key, min_role="viewer")
    job = await _get_job(session, ctx, job_id)
    return await _job_payload(session, job)


@router.get("/jobs/{job_id}/steps/{ordinal}/log", response_model=LogTailOut)
async def get_step_log(
    key: str,
    job_id: str,
    ordinal: int,
    request: Request,
    user: CurrentUser,
    session: DbSession,
    after: int = 0,
) -> dict[str, Any]:
    ctx = await load_project_context(session, user, key, min_role="viewer")
    job = await _get_job(session, ctx, job_id)
    step = (
        await session.execute(
            select(JobStep).where(JobStep.job_id == job.id, JobStep.ordinal == ordinal)
        )
    ).scalar_one_or_none()
    if step is None:
        raise Problem(
            404,
            title="Step not found",
            detail="No such step on this job.",
            hint="Check the step ordinal.",
            slug="not-found",
        )
    storage: Storage = request.app.state.storage
    prefix = step_log_prefix(ctx.project.key, job.id, ordinal)
    after = max(0, after)
    return await run_engine(lambda: read_step_log(storage, prefix, after=after))


# ── Cancel ───────────────────────────────────────────────────────────────────────


@router.post("/jobs/{job_id}/cancel", response_model=JobOut)
async def cancel_job(
    key: str, job_id: str, request: Request, user: CurrentUser, session: DbSession
) -> dict[str, Any]:
    ctx = await load_project_context(session, user, key, min_role="editor")
    # Lock the row so a cancel never races the worker's heartbeat/finalize on this job.
    try:
        parsed = uuid.UUID(job_id)
    except ValueError as exc:
        raise Problem(
            404,
            title="Job not found",
            detail="No such job in this project.",
            hint="Check the job id.",
            slug="not-found",
        ) from exc
    job = (
        await session.execute(
            select(Job).where(Job.id == parsed, Job.project_id == ctx.project.id).with_for_update()
        )
    ).scalar_one_or_none()
    if job is None:
        raise Problem(
            404,
            title="Job not found",
            detail="No such job in this project.",
            hint="Check the job id.",
            slug="not-found",
        )

    if job.status in _ACTIVE:
        job.cancel_requested = True
        if job.status == "queued":
            # Not yet claimed: cancel outright and skip every step.
            job.status = "cancelled"
            job.finished_at = datetime.datetime.now(datetime.UTC)
            await session.execute(
                update(JobStep)
                .where(JobStep.job_id == job.id, JobStep.status.in_(_ACTIVE))
                .values(status="skipped", finished_at=datetime.datetime.now(datetime.UTC))
            )
        # A running job keeps its status until the worker's cancel-poll interrupts the
        # live step and finalizes it (ADR-0007 §1).
        await publish_event(
            session,
            topic="jobs",
            type="job.updated",
            project_id=ctx.project.id,
            payload={"id": str(job.id), "status": job.status},
        )
        await write_audit(
            session,
            actor_id=user.id,
            project_id=ctx.project.id,
            action="build.cancelled",
            object_kind="job",
            object_id=str(job.id),
            details={"status": job.status},
            ip=_client_ip(request),
        )
    await session.commit()
    return await _job_payload(session, job)
