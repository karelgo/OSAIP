"""GET /events — the single multiplexed SSE channel (§6.6, ADR-0003)."""

import asyncio
import datetime
import json
import time
import uuid
from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sse_starlette.sse import EventSourceResponse

from osaip_api.auth.deps import current_user
from osaip_api.events import current_head, fetch_events_after, min_available_seq
from osaip_api.models import Event, ProjectMember, User

router = APIRouter(tags=["events"])

_MEMBERSHIP_TTL_SECONDS = 10.0
_WAKE_TIMEOUT_SECONDS = 5.0


class _Visibility:
    """Membership-cached visibility predicate — the ONE filter used for live tail
    and replay alike (ADR-0003)."""

    def __init__(self, user: User) -> None:
        self._user = user
        self._projects: set[uuid.UUID] = set()
        self._loaded_at = 0.0

    async def _project_ids(self, request: Request) -> set[uuid.UUID]:
        if time.monotonic() - self._loaded_at > _MEMBERSHIP_TTL_SECONDS:
            async with request.app.state.sessionmaker() as session:
                rows = (
                    await session.execute(
                        select(ProjectMember.project_id).where(
                            ProjectMember.user_id == self._user.id
                        )
                    )
                ).scalars()
                self._projects = set(rows)
            self._loaded_at = time.monotonic()
        return self._projects

    async def visible(self, request: Request, event: Event) -> bool:
        if event.user_id is not None:
            return event.user_id == self._user.id
        if event.project_id is not None:
            if self._user.is_site_admin:
                return True
            return event.project_id in await self._project_ids(request)
        return True


def _serialize(event: Event) -> dict[str, Any]:
    return {
        "id": str(event.seq),
        "event": event.topic,
        "data": json.dumps(
            {
                "type": event.type,
                "topic": event.topic,
                "project_id": str(event.project_id) if event.project_id else None,
                "payload": event.payload,
                "ts": event.ts.astimezone(datetime.UTC).isoformat(),
            }
        ),
    }


@router.get("/events")
async def events_stream(
    request: Request,
    user: Annotated[User, Depends(current_user)],
    topics: str | None = None,
) -> EventSourceResponse:
    wanted_topics = set(topics.split(",")) if topics else None
    visibility = _Visibility(user)
    broker = request.app.state.event_broker
    last_event_id = request.headers.get("last-event-id")

    async def stream() -> AsyncIterator[dict[str, Any]]:
        waiter = broker.subscribe()
        try:
            async with request.app.state.sessionmaker() as session:
                if last_event_id is not None:
                    cursor = int(last_event_id)
                    oldest = await min_available_seq(session)
                    if oldest is not None and cursor + 1 < oldest:
                        # Cursor predates retention: tell the client to refetch
                        # everything and resume from the head (ADR-0003).
                        cursor = await current_head(session)
                        yield {"id": str(cursor), "event": "control", "data": '{"type":"reset"}'}
                else:
                    cursor = await current_head(session)

            while True:
                async with request.app.state.sessionmaker() as session:
                    batch = await fetch_events_after(session, cursor)
                for event in batch:
                    cursor = event.seq  # advance past invisible events too
                    if wanted_topics is not None and event.topic not in wanted_topics:
                        continue
                    if await visibility.visible(request, event):
                        yield _serialize(event)
                if len(batch) == 500:
                    continue  # more rows may be waiting; don't sleep yet
                try:
                    await asyncio.wait_for(waiter.wait(), timeout=_WAKE_TIMEOUT_SECONDS)
                except TimeoutError:
                    pass
                waiter.clear()
        finally:
            broker.unsubscribe(waiter)

    return EventSourceResponse(stream(), ping=15)
