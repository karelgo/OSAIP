"""Dev-only helpers — mounted ONLY when OSAIP_DEV=1 (never in production)."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from osaip_api.auth.deps import CurrentUser
from osaip_api.db import get_session
from osaip_api.notifications import notify
from osaip_api.schemas import EmitTestEventOut

router = APIRouter(prefix="/dev", tags=["dev"])

DbSession = Annotated[AsyncSession, Depends(get_session)]


@router.post("/emit-test-event", response_model=EmitTestEventOut)
async def emit_test_event(user: CurrentUser, session: DbSession) -> dict[str, Any]:
    """Drives spec §7 Phase 0 AC-7: a test event arrives as toast + inbox item over SSE."""
    notification = await notify(
        session,
        user_id=user.id,
        kind="test",
        severity="info",
        title="Test event received",
        body="This is a test notification delivered over the SSE event bus.",
    )
    await session.commit()
    return {"notification_id": str(notification.id)}
