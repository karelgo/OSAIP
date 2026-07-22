"""SSE bus tests: live tail, Last-Event-ID replay, visibility, notifications wiring."""

import asyncio
import json
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
import pytest
from httpx_sse import aconnect_sse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from osaip_api.events import publish_event
from osaip_api.notifications import notify

LoginAs = Callable[..., Awaitable[httpx.AsyncClient]]


async def _collect_events(
    client: httpx.AsyncClient,
    count: int,
    *,
    headers: dict[str, str] | None = None,
    ready: asyncio.Event | None = None,
    max_wait: float = 10.0,
) -> list[dict[str, Any]]:
    """Open the stream and gather `count` non-comment events (excluding control unless
    counted by caller)."""
    received: list[dict[str, Any]] = []

    async def consume() -> None:
        async with aconnect_sse(
            client,
            "GET",
            "/api/v1/events",
            headers=headers or {},
            timeout=httpx.Timeout(10.0, read=15.0),
        ) as source:
            if ready is not None:
                ready.set()
            async for sse in source.aiter_sse():
                received.append({"id": sse.id, "event": sse.event, "data": json.loads(sse.data)})
                if len(received) >= count:
                    return

    await asyncio.wait_for(consume(), timeout=max_wait)
    return received


async def test_live_event_arrives_with_seq_id(
    login_as_http: LoginAs, db_session: AsyncSession
) -> None:
    client = await login_as_http("sse-1", "sse1@osaip.dev")

    ready = asyncio.Event()
    task = asyncio.create_task(_collect_events(client, 1, ready=ready))
    await asyncio.wait_for(ready.wait(), timeout=5)
    await asyncio.sleep(0.2)  # let the stream compute its head cursor

    event = await publish_event(db_session, topic="jobs", type="job.test", payload={"n": 1})
    await db_session.commit()

    events = await asyncio.wait_for(task, timeout=10)
    assert events[0]["event"] == "jobs"
    assert events[0]["id"] == str(event.seq)
    assert events[0]["data"]["type"] == "job.test"


async def test_last_event_id_replays_missed_events(
    login_as_http: LoginAs, db_session: AsyncSession
) -> None:
    client = await login_as_http("sse-2", "sse2@osaip.dev")

    first = await publish_event(db_session, topic="jobs", type="job.a")
    await db_session.commit()
    second = await publish_event(db_session, topic="jobs", type="job.b")
    await db_session.commit()
    third = await publish_event(db_session, topic="jobs", type="job.c")
    await db_session.commit()

    events = await _collect_events(client, 2, headers={"Last-Event-ID": str(first.seq)})
    assert [item["id"] for item in events] == [str(second.seq), str(third.seq)]
    assert [item["data"]["type"] for item in events] == ["job.b", "job.c"]


async def test_user_targeted_events_are_private(
    login_as_http: LoginAs, db_session: AsyncSession
) -> None:
    alice = await login_as_http("sse-alice", "sse-alice@osaip.dev")
    bob = await login_as_http("sse-bob", "sse-bob@osaip.dev")
    bob_user_id = (await bob.get("/api/v1/me")).json()["id"]

    marker = await publish_event(db_session, topic="jobs", type="public.marker")
    await db_session.commit()

    # One private event for bob, then a public marker so alice's stream progresses.
    await publish_event(
        db_session,
        topic="notifications",
        type="private.for-bob",
        user_id=uuid.UUID(bob_user_id),
    )
    await db_session.commit()
    await publish_event(db_session, topic="jobs", type="public.after")
    await db_session.commit()

    since = {"Last-Event-ID": str(marker.seq)}
    alice_events = await _collect_events(alice, 1, headers=since)
    assert [item["data"]["type"] for item in alice_events] == ["public.after"]

    bob_events = await _collect_events(bob, 2, headers=since)
    assert [item["data"]["type"] for item in bob_events] == [
        "private.for-bob",
        "public.after",
    ]


async def test_project_events_respect_membership(
    login_as_http: LoginAs, db_session: AsyncSession
) -> None:
    member = await login_as_http("sse-member", "sse-member@osaip.dev")
    outsider = await login_as_http("sse-outsider", "sse-outsider@osaip.dev")
    created = await member.post(
        "/api/v1/projects",
        json={"key": "sse-proj-1", "name": "SSE Project", "description": ""},
    )
    assert created.status_code == 201

    marker = await publish_event(db_session, topic="jobs", type="marker.projects")
    await db_session.commit()

    project_id = (
        await db_session.execute(text("SELECT id FROM projects WHERE key='sse-proj-1'"))
    ).scalar_one()
    await publish_event(
        db_session, topic="projects", type="project.touched", project_id=uuid.UUID(str(project_id))
    )
    await db_session.commit()
    await publish_event(db_session, topic="jobs", type="public.tail")
    await db_session.commit()

    since = {"Last-Event-ID": str(marker.seq)}
    member_events = await _collect_events(member, 2, headers=since)
    assert [item["data"]["type"] for item in member_events] == [
        "project.touched",
        "public.tail",
    ]
    outsider_events = await _collect_events(outsider, 1, headers=since)
    assert [item["data"]["type"] for item in outsider_events] == ["public.tail"]


async def test_stale_cursor_gets_reset_control_event(login_as_http: LoginAs) -> None:
    client = await login_as_http("sse-3", "sse3@osaip.dev")
    # Cursor far below the minimum available seq (0 works once any event exists,
    # as long as seq 1 has been pruned — simulate by asking from a negative cursor).
    events = await _collect_events(client, 1, headers={"Last-Event-ID": "-100"})
    assert events[0]["event"] == "control"
    assert events[0]["data"]["type"] == "reset"


async def test_dev_emit_creates_notification_and_event(login_as_http: LoginAs) -> None:
    client = await login_as_http("sse-4", "sse4@osaip.dev")

    ready = asyncio.Event()
    task = asyncio.create_task(_collect_events(client, 1, ready=ready))
    await asyncio.wait_for(ready.wait(), timeout=5)
    await asyncio.sleep(0.2)

    emitted = await client.post("/api/v1/dev/emit-test-event")
    assert emitted.status_code == 200

    events = await asyncio.wait_for(task, timeout=10)
    assert events[0]["event"] == "notifications"
    assert events[0]["data"]["type"] == "notification.created"
    assert events[0]["data"]["payload"]["title"] == "Test event received"

    inbox = (await client.get("/api/v1/notifications")).json()
    assert inbox["unread_count"] >= 1
    assert any(item["kind"] == "test" for item in inbox["items"])


async def test_notifications_read_flow(login_as_http: LoginAs, db_session: AsyncSession) -> None:
    client = await login_as_http("sse-5", "sse5@osaip.dev")
    user_id = (await client.get("/api/v1/me")).json()["id"]

    await notify(
        session=db_session,
        user_id=uuid.UUID(user_id),
        kind="job",
        title="Build finished",
        severity="success",
    )
    await db_session.commit()

    inbox = (await client.get("/api/v1/notifications")).json()
    assert inbox["unread_count"] == 1
    notification_id = inbox["items"][0]["id"]

    read = await client.post(f"/api/v1/notifications/{notification_id}/read")
    assert read.status_code == 200
    assert read.json()["read_at"] is not None

    await notify(session=db_session, user_id=uuid.UUID(user_id), kind="job", title="Another")
    await db_session.commit()
    marked = (await client.post("/api/v1/notifications/read-all")).json()
    assert marked["marked_read"] == 1
    assert (await client.get("/api/v1/notifications")).json()["unread_count"] == 0


async def test_foreign_notification_is_unreachable(login_as_http: LoginAs) -> None:
    owner = await login_as_http("sse-6", "sse6@osaip.dev")
    stranger = await login_as_http("sse-7", "sse7@osaip.dev")
    assert (await owner.post("/api/v1/dev/emit-test-event")).status_code == 200
    inbox = (await owner.get("/api/v1/notifications")).json()
    notification_id = inbox["items"][0]["id"]
    forbidden = await stranger.post(f"/api/v1/notifications/{notification_id}/read")
    assert forbidden.status_code == 404


@pytest.mark.parametrize(
    ("q", "expect_hit"), [("SSE", True), ("search-proj", True), ("zzzzzz", False)]
)
async def test_search_finds_membership_scoped_objects(
    login_as: LoginAs, q: str, expect_hit: bool
) -> None:
    member = await login_as("search-1", "search1@osaip.dev")
    outsider = await login_as("search-2", "search2@osaip.dev")
    created = await member.post(
        "/api/v1/projects",
        json={"key": "search-proj-1", "name": "SSE Search Target", "description": "findable"},
    )
    assert created.status_code in (201, 409)  # idempotent across param runs

    hits = (await member.get("/api/v1/search", params={"q": q})).json()["items"]
    assert any(item["url_path"] == "/p/search-proj-1" for item in hits) is expect_hit

    if expect_hit:
        outsider_hits = (await outsider.get("/api/v1/search", params={"q": q})).json()["items"]
        assert not any(item["url_path"] == "/p/search-proj-1" for item in outsider_hits)
