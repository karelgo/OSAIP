"""Cache key discipline, TTL, and the no-cache purposes.

The key tests are the isolation ones: two projects sharing a global connection must
never see each other's completions, and a non-deterministic request must not be served
from a store.
"""

import datetime
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from osaip_api.models import LlmCache
from osaip_mesh.cache import cache_lookup, cache_store, compute_request_hash, is_cacheable
from osaip_mesh.providers.base import CompletionRequest, Message
from osaip_shared.ids import new_id


def _request(content: str = "hello", **overrides: float | int | str) -> CompletionRequest:
    return CompletionRequest(
        model=str(overrides.get("model", "echo-1")),
        messages=[Message(role="user", content=content)],
        max_tokens=int(overrides.get("max_tokens", 512)),
        temperature=float(overrides.get("temperature", 0.0)),
    )


def _hash(
    request: CompletionRequest,
    *,
    connection_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
) -> str:
    return compute_request_hash(
        connection_id=connection_id,
        project_id=project_id,
        request=request,
        redacted_messages=request.messages,
    )


def test_same_request_hashes_identically() -> None:
    connection_id = new_id()
    assert _hash(_request(), connection_id=connection_id) == _hash(
        _request(), connection_id=connection_id
    )


def test_project_is_part_of_the_key() -> None:
    """A global connection is shared; one project must not be served another's answer."""
    connection_id = new_id()
    a = _hash(_request(), connection_id=connection_id, project_id=new_id())
    b = _hash(_request(), connection_id=connection_id, project_id=new_id())
    assert a != b


@pytest.mark.parametrize("kwargs", [{"model": "echo-2"}, {"max_tokens": 256}, {"temperature": 0.7}])
def test_every_answer_changing_field_changes_the_key(kwargs: dict[str, float | int | str]) -> None:
    assert _hash(_request()) != _hash(_request(**kwargs))


def test_content_changes_the_key() -> None:
    assert _hash(_request("hello")) != _hash(_request("goodbye"))


def test_connection_is_part_of_the_key() -> None:
    assert _hash(_request(), connection_id=new_id()) != _hash(_request(), connection_id=new_id())


@pytest.mark.parametrize(
    ("ttl_s", "purpose", "temperature", "expected"),
    [
        (300, "general", 0.0, True),
        (0, "general", 0.0, False),  # disabled
        (-1, "general", 0.0, False),
        (300, "guardrail", 0.0, False),  # a moderation verdict must not be cached
        (300, "eval", 0.0, False),  # nor an eval run
        (300, "general", 0.7, False),  # the caller asked for variation
    ],
)
def test_cacheability_rules(ttl_s: int, purpose: str, temperature: float, expected: bool) -> None:
    assert is_cacheable(ttl_s=ttl_s, purpose=purpose, temperature=temperature) is expected


async def test_store_then_lookup_round_trip(mesh_session: AsyncSession) -> None:
    request_hash = _hash(_request())
    await cache_store(
        mesh_session,
        request_hash=request_hash,
        connection_id=None,
        project_id=None,
        content="cached answer",
        tokens_in=3,
        tokens_out=4,
        model_version="echo-1@echo-1",
        ttl_s=300,
    )
    await mesh_session.commit()

    hit = await cache_lookup(mesh_session, request_hash)
    assert hit is not None
    assert hit.content == "cached answer"
    assert (hit.tokens_in, hit.tokens_out) == (3, 4)
    assert hit.model_version == "echo-1@echo-1"


async def test_expired_entries_are_never_served(mesh_session: AsyncSession) -> None:
    """Expiry is enforced in the read, so a late sweep cannot hand back a stale answer."""
    request_hash = _hash(_request("stale"))
    mesh_session.add(
        LlmCache(
            request_hash=request_hash,
            connection_id=None,
            project_id=None,
            response_json={"content": "old"},
            tokens_in=1,
            tokens_out=1,
            expires_at=datetime.datetime.now(datetime.UTC) - datetime.timedelta(seconds=1),
        )
    )
    await mesh_session.commit()
    assert await cache_lookup(mesh_session, request_hash) is None


async def test_store_is_idempotent_and_refreshes_the_entry(mesh_session: AsyncSession) -> None:
    request_hash = _hash(_request("racy"))
    for content in ("first", "second"):
        await cache_store(
            mesh_session,
            request_hash=request_hash,
            connection_id=None,
            project_id=None,
            content=content,
            tokens_in=1,
            tokens_out=1,
            model_version=None,
            ttl_s=300,
        )
    await mesh_session.commit()
    hit = await cache_lookup(mesh_session, request_hash)
    assert hit is not None and hit.content == "second"


async def test_unreadable_entry_is_treated_as_a_miss(mesh_session: AsyncSession) -> None:
    request_hash = _hash(_request("broken"))
    mesh_session.add(
        LlmCache(
            request_hash=request_hash,
            response_json={"unexpected": True},
            tokens_in=0,
            tokens_out=0,
            expires_at=datetime.datetime.now(datetime.UTC) + datetime.timedelta(seconds=60),
        )
    )
    await mesh_session.commit()
    assert await cache_lookup(mesh_session, request_hash) is None
