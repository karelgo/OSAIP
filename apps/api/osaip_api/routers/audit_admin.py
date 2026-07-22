"""Site-wide audit access + chain verification (site admin only; CP-7)."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from osaip_api.audit import verify_chain
from osaip_api.auth.deps import CurrentUser
from osaip_api.db import get_session
from osaip_api.models import AuditLog
from osaip_api.permissions import require_site_admin

router = APIRouter(tags=["audit"])

DbSession = Annotated[AsyncSession, Depends(get_session)]


@router.get("/audit")
async def list_audit(
    user: CurrentUser,
    session: DbSession,
    limit: int = 100,
    before_seq: int | None = None,
) -> dict[str, Any]:
    require_site_admin(user)
    limit = max(1, min(limit, 500))
    query = select(AuditLog).order_by(AuditLog.seq.desc()).limit(limit + 1)
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
                "project_id": str(row.project_id) if row.project_id else None,
                "action": row.action,
                "object_kind": row.object_kind,
                "object_id": row.object_id,
                "details": row.details,
            }
            for row in rows
        ],
        "next_before_seq": rows[-1].seq if has_more and rows else None,
    }


@router.post("/audit/verify")
async def verify_audit_chain(user: CurrentUser, session: DbSession) -> dict[str, Any]:
    require_site_admin(user)
    result = await verify_chain(session)
    return {
        "ok": result.ok,
        "checked": result.checked,
        "first_bad_seq": result.first_bad_seq,
        "reason": result.reason,
    }
