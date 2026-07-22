"""GET /search — ⌘K object search over the object_refs registry (§6.6).

Phase 0: Postgres FTS with prefix matching, membership-filtered. The pgvector half of
the hybrid arrives in Phase 3 with the mesh (ADR-0005).
"""

import re
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from osaip_api.auth.deps import CurrentUser
from osaip_api.db import get_session
from osaip_api.models import ObjectRef, Project, ProjectMember

router = APIRouter(tags=["search"])

DbSession = Annotated[AsyncSession, Depends(get_session)]


def _prefix_tsquery(q: str) -> str:
    words = re.findall(r"\w+", q, flags=re.UNICODE)[:8]
    return " & ".join(f"{word}:*" for word in words)


@router.get("/search")
async def search(
    user: CurrentUser,
    session: DbSession,
    q: str = "",
    project: str | None = None,
    kinds: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    q = q.strip()
    if not q:
        return {"items": []}
    limit = max(1, min(limit, 50))

    tsquery = func.to_tsquery("simple", _prefix_tsquery(q))
    query = (
        select(ObjectRef, Project.key)
        .join(Project, Project.id == ObjectRef.project_id, isouter=True)
        .where(ObjectRef.tsv.op("@@")(tsquery))
        .order_by(func.ts_rank(ObjectRef.tsv, tsquery).desc(), ObjectRef.name)
        .limit(limit)
    )
    if not user.is_site_admin:
        membership = select(ProjectMember.project_id).where(ProjectMember.user_id == user.id)
        query = query.where(
            or_(ObjectRef.project_id.is_(None), ObjectRef.project_id.in_(membership))
        )
    if project:
        query = query.where(Project.key == project)
    if kinds:
        query = query.where(ObjectRef.kind.in_(kinds.split(",")))

    rows = (await session.execute(query)).all()
    return {
        "items": [
            {
                "kind": ref.kind,
                "name": ref.name,
                "description": ref.description,
                "url_path": ref.url_path,
                "project_key": project_key,
            }
            for ref, project_key in rows
        ]
    }
