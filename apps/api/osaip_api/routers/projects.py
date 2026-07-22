"""Projects CRUD, membership, and per-project audit (spec §7 Phase 0)."""

import base64
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from osaip_api.audit import write_audit
from osaip_api.auth.deps import CurrentUser
from osaip_api.db import get_session
from osaip_api.etag import etag_json_response
from osaip_api.idempotency import check_idempotency, store_idempotent_response
from osaip_api.models import AuditLog, ObjectRef, Project, ProjectMember, User
from osaip_api.permissions import (
    ProjectContext,
    load_project_context,
    membership_role,
    project_payload,
)
from osaip_api.problem import Problem

router = APIRouter(prefix="/projects", tags=["projects"])

DbSession = Annotated[AsyncSession, Depends(get_session)]


class ProjectCreate(BaseModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,63}$")
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=10_000)


class ProjectPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=10_000)


class MemberIn(BaseModel):
    email: EmailStr
    role: str = Field(pattern="^(viewer|editor|admin)$")


class MembersPut(BaseModel):
    members: list[MemberIn] = Field(min_length=1)


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _encode_cursor(key: str) -> str:
    return base64.urlsafe_b64encode(key.encode()).decode()


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


@router.get("")
async def list_projects(
    request: Request,
    user: CurrentUser,
    session: DbSession,
    limit: int = 50,
    cursor: str | None = None,
) -> Response:
    limit = max(1, min(limit, 200))
    query = select(Project).order_by(Project.key).limit(limit + 1)
    if not user.is_site_admin:
        query = query.join(
            ProjectMember,
            (ProjectMember.project_id == Project.id) & (ProjectMember.user_id == user.id),
        )
    if cursor:
        query = query.where(Project.key > _decode_cursor(cursor))
    projects = (await session.execute(query)).scalars().all()

    has_more = len(projects) > limit
    projects = projects[:limit]
    items: list[dict[str, Any]] = []
    for project in projects:
        role = await membership_role(session, user, project)
        items.append(project_payload(ProjectContext(project=project, role=role or "viewer")))
    payload = {
        "items": items,
        "next_cursor": _encode_cursor(projects[-1].key) if has_more and projects else None,
    }
    return etag_json_response(request, payload)


@router.post("", status_code=201)
async def create_project(
    body: ProjectCreate, request: Request, user: CurrentUser, session: DbSession
) -> JSONResponse:
    idem_key, req_hash, stored = await check_idempotency(session, request, user, body.model_dump())
    if stored is not None:
        return JSONResponse(content=stored[1], status_code=stored[0])

    existing = (
        await session.execute(select(Project).where(Project.key == body.key))
    ).scalar_one_or_none()
    if existing is not None:
        raise Problem(
            409,
            title="Project key taken",
            detail=f"A project with key {body.key!r} already exists.",
            hint="Pick a different key; keys are permanent identifiers.",
            slug="project-key-taken",
        )

    project = Project(
        key=body.key,
        name=body.name,
        description=body.description,
        storage_prefix=f"projects/{body.key}",
        created_by=user.id,
    )
    session.add(project)
    await session.flush()
    session.add(ProjectMember(project_id=project.id, user_id=user.id, role="admin"))
    session.add(
        ObjectRef(
            kind="project",
            project_id=project.id,
            name=body.name,
            # Key is part of the searchable text so ⌘K finds projects by key too.
            description=f"{body.key} {body.description}".strip(),
            url_path=f"/p/{body.key}",
        )
    )
    await write_audit(
        session,
        actor_id=user.id,
        project_id=project.id,
        action="project.created",
        object_kind="project",
        object_id=body.key,
        details={"name": body.name},
        ip=_client_ip(request),
    )

    ctx = ProjectContext(project=project, role="admin")
    payload = project_payload(ctx)
    if idem_key is not None:
        await store_idempotent_response(session, user, idem_key, request, req_hash, 201, payload)
    await session.commit()
    return JSONResponse(content=payload, status_code=201)


@router.get("/{key}")
async def get_project(
    key: str, request: Request, user: CurrentUser, session: DbSession
) -> Response:
    ctx = await load_project_context(session, user, key, min_role="viewer")
    return etag_json_response(request, project_payload(ctx))


@router.patch("/{key}")
async def patch_project(
    key: str, body: ProjectPatch, request: Request, user: CurrentUser, session: DbSession
) -> dict[str, Any]:
    ctx = await load_project_context(session, user, key, min_role="editor")
    if ctx.project.status != "active":
        raise _archived_problem(key)
    changed: dict[str, Any] = {}
    if body.name is not None and body.name != ctx.project.name:
        changed["name"] = body.name
        ctx.project.name = body.name
    if body.description is not None and body.description != ctx.project.description:
        changed["description"] = "updated"
        ctx.project.description = body.description
    if changed:
        ref = (
            await session.execute(
                select(ObjectRef).where(
                    ObjectRef.kind == "project", ObjectRef.project_id == ctx.project.id
                )
            )
        ).scalar_one_or_none()
        if ref is not None:
            ref.name = ctx.project.name
            ref.description = f"{ctx.project.key} {ctx.project.description}".strip()
        await write_audit(
            session,
            actor_id=user.id,
            project_id=ctx.project.id,
            action="project.updated",
            object_kind="project",
            object_id=key,
            details=changed,
            ip=_client_ip(request),
        )
        await session.commit()
        # updated_at is server-generated on UPDATE; re-read it before serializing
        await session.refresh(ctx.project)
    return project_payload(ctx)


@router.delete("/{key}")
async def archive_project(
    key: str, request: Request, user: CurrentUser, session: DbSession
) -> dict[str, Any]:
    ctx = await load_project_context(session, user, key, min_role="admin")
    if ctx.project.status == "archived":
        raise _archived_problem(key)
    ctx.project.status = "archived"
    # Archived projects leave the ⌘K registry.
    ref = (
        await session.execute(
            select(ObjectRef).where(
                ObjectRef.kind == "project", ObjectRef.project_id == ctx.project.id
            )
        )
    ).scalar_one_or_none()
    if ref is not None:
        await session.delete(ref)
    await write_audit(
        session,
        actor_id=user.id,
        project_id=ctx.project.id,
        action="project.archived",
        object_kind="project",
        object_id=key,
        ip=_client_ip(request),
    )
    await session.commit()
    await session.refresh(ctx.project)
    return project_payload(ctx)


def _archived_problem(key: str) -> Problem:
    return Problem(
        409,
        title="Project is archived",
        detail=f"Project {key!r} is archived; archived projects are read-only.",
        hint="Ask a site administrator to restore it if needed.",
        slug="project-archived",
    )


@router.get("/{key}/members")
async def list_members(key: str, user: CurrentUser, session: DbSession) -> dict[str, Any]:
    ctx = await load_project_context(session, user, key, min_role="viewer")
    rows = (
        await session.execute(
            select(ProjectMember, User)
            .join(User, User.id == ProjectMember.user_id)
            .where(ProjectMember.project_id == ctx.project.id)
            .order_by(User.email)
        )
    ).all()
    return {
        "items": [
            {
                "user_id": str(member.user_id),
                "email": member_user.email,
                "display_name": member_user.display_name,
                "role": member.role,
            }
            for member, member_user in rows
        ]
    }


@router.put("/{key}/members")
async def replace_members(
    key: str, body: MembersPut, request: Request, user: CurrentUser, session: DbSession
) -> dict[str, Any]:
    ctx = await load_project_context(session, user, key, min_role="admin")
    if ctx.project.status != "active":
        raise _archived_problem(key)
    if not any(member.role == "admin" for member in body.members):
        raise _needs_admin_problem()

    desired: dict[str, str] = {}
    for member in body.members:
        target = (
            await session.execute(select(User).where(User.email == member.email))
        ).scalar_one_or_none()
        if target is None:
            raise Problem(
                422,
                title="Unknown user",
                detail=f"No user with email {member.email!r} exists yet.",
                hint="Users appear after their first sign-in.",
                slug="unknown-user",
            )
        desired[str(target.id)] = member.role

    current = (
        (
            await session.execute(
                select(ProjectMember).where(ProjectMember.project_id == ctx.project.id)
            )
        )
        .scalars()
        .all()
    )
    for row in current:
        if str(row.user_id) not in desired:
            await session.delete(row)
        elif row.role != desired[str(row.user_id)]:
            row.role = desired.pop(str(row.user_id))
        else:
            desired.pop(str(row.user_id))
    for user_id, role in desired.items():
        session.add(ProjectMember(project_id=ctx.project.id, user_id=user_id, role=role))

    await write_audit(
        session,
        actor_id=user.id,
        project_id=ctx.project.id,
        action="project.members_replaced",
        object_kind="project",
        object_id=key,
        details={"members": [{"email": m.email, "role": m.role} for m in body.members]},
        ip=_client_ip(request),
    )
    await session.commit()
    return await list_members(key, user, session)


@router.delete("/{key}/members/{user_id}")
async def remove_member(
    key: str, user_id: str, request: Request, user: CurrentUser, session: DbSession
) -> dict[str, Any]:
    ctx = await load_project_context(session, user, key, min_role="admin")
    if ctx.project.status != "active":
        raise _archived_problem(key)
    row = (
        await session.execute(
            select(ProjectMember).where(
                ProjectMember.project_id == ctx.project.id, ProjectMember.user_id == user_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise Problem(
            404,
            title="Member not found",
            detail="That user is not a member of this project.",
            hint="Refresh the member list.",
            slug="not-found",
        )
    if row.role == "admin":
        admins = (
            (
                await session.execute(
                    select(ProjectMember).where(
                        ProjectMember.project_id == ctx.project.id,
                        ProjectMember.role == "admin",
                    )
                )
            )
            .scalars()
            .all()
        )
        if len(admins) <= 1:
            raise _needs_admin_problem()
    await session.delete(row)
    await write_audit(
        session,
        actor_id=user.id,
        project_id=ctx.project.id,
        action="project.member_removed",
        object_kind="project",
        object_id=key,
        details={"user_id": user_id},
        ip=_client_ip(request),
    )
    await session.commit()
    return await list_members(key, user, session)


def _needs_admin_problem() -> Problem:
    return Problem(
        409,
        title="Project needs an admin",
        detail="A project must keep at least one admin member.",
        hint="Assign the admin role to another member first.",
        slug="last-admin",
    )


@router.get("/{key}/audit")
async def project_audit(
    key: str,
    user: CurrentUser,
    session: DbSession,
    limit: int = 50,
    before_seq: int | None = None,
) -> dict[str, Any]:
    ctx = await load_project_context(session, user, key, min_role="viewer")
    limit = max(1, min(limit, 200))
    query = (
        select(AuditLog)
        .where(AuditLog.project_id == ctx.project.id)
        .order_by(AuditLog.seq.desc())
        .limit(limit + 1)
    )
    if before_seq is not None:
        query = query.where(AuditLog.seq < before_seq)
    rows = (await session.execute(query)).scalars().all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    return {
        "items": [
            {
                "seq": row.seq,
                "ts": row.ts.isoformat(),
                "actor_id": str(row.actor_id) if row.actor_id else None,
                "action": row.action,
                "object_kind": row.object_kind,
                "object_id": row.object_id,
                "details": row.details,
            }
            for row in rows
        ],
        "next_before_seq": rows[-1].seq if has_more and rows else None,
    }
