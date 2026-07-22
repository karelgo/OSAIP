"""Notifications inbox (§6.6)."""

import datetime
import uuid
from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends
from sqlalchemy import CursorResult, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from osaip_api.auth.deps import CurrentUser
from osaip_api.db import get_session
from osaip_api.models import Notification
from osaip_api.problem import Problem
from osaip_api.schemas import MarkAllReadOut, NotificationListOut, NotificationOut

router = APIRouter(prefix="/notifications", tags=["notifications"])

DbSession = Annotated[AsyncSession, Depends(get_session)]


def _serialize(notification: Notification) -> dict[str, Any]:
    return {
        "id": str(notification.id),
        "kind": notification.kind,
        "severity": notification.severity,
        "title": notification.title,
        "body": notification.body,
        "ref_kind": notification.ref_kind,
        "ref_id": notification.ref_id,
        "created_at": notification.created_at.isoformat(),
        "read_at": notification.read_at.isoformat() if notification.read_at else None,
    }


@router.get("", response_model=NotificationListOut)
async def list_notifications(
    user: CurrentUser, session: DbSession, limit: int = 50, unread_only: bool = False
) -> dict[str, Any]:
    limit = max(1, min(limit, 200))
    query = (
        select(Notification)
        .where(Notification.user_id == user.id)
        .order_by(Notification.created_at.desc())
        .limit(limit)
    )
    if unread_only:
        query = query.where(Notification.read_at.is_(None))
    rows = (await session.execute(query)).scalars().all()
    unread = (
        await session.execute(
            select(Notification.id)
            .where(Notification.user_id == user.id, Notification.read_at.is_(None))
            .limit(100)
        )
    ).all()
    return {"items": [_serialize(row) for row in rows], "unread_count": len(unread)}


@router.post("/{notification_id}/read", response_model=NotificationOut)
async def mark_read(
    notification_id: uuid.UUID, user: CurrentUser, session: DbSession
) -> dict[str, Any]:
    row = (
        await session.execute(
            select(Notification).where(
                Notification.id == notification_id, Notification.user_id == user.id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise Problem(
            404,
            title="Notification not found",
            detail="That notification does not exist (or is not yours).",
            hint="Refresh the inbox.",
            slug="not-found",
        )
    if row.read_at is None:
        row.read_at = datetime.datetime.now(datetime.UTC)
        await session.commit()
    return _serialize(row)


@router.post("/read-all", response_model=MarkAllReadOut)
async def mark_all_read(user: CurrentUser, session: DbSession) -> dict[str, int]:
    result = cast(
        CursorResult[Any],
        await session.execute(
            update(Notification)
            .where(Notification.user_id == user.id, Notification.read_at.is_(None))
            .values(read_at=datetime.datetime.now(datetime.UTC))
        ),
    )
    await session.commit()
    return {"marked_read": result.rowcount or 0}
