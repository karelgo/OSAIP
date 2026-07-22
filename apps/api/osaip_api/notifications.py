"""Notification creation — always paired with an SSE event so the inbox badge and
toasts update live."""

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from osaip_api.events import publish_event
from osaip_api.models import Notification


async def notify(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    kind: str,
    title: str,
    body: str = "",
    severity: str = "info",
    ref_kind: str | None = None,
    ref_id: str | None = None,
) -> Notification:
    notification = Notification(
        user_id=user_id,
        kind=kind,
        severity=severity,
        title=title,
        body=body,
        ref_kind=ref_kind,
        ref_id=ref_id,
    )
    session.add(notification)
    await session.flush()
    payload: dict[str, Any] = {
        "notification_id": str(notification.id),
        "kind": kind,
        "severity": severity,
        "title": title,
        "body": body,
        "ref_kind": ref_kind,
        "ref_id": ref_id,
    }
    await publish_event(
        session,
        topic="notifications",
        type="notification.created",
        user_id=user_id,
        payload=payload,
    )
    return notification
