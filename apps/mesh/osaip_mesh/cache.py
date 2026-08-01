"""Response cache, keyed on the REDACTED request (ADR-0008 §4).

Two properties matter more than the hit rate:

1. The key is computed AFTER the `pre` guardrails redact, so raw PII never becomes a
   cache key — and a cache hit still yields a redacted audit trail.
2. `project_id` is part of the key. A global connection is shared across projects, and
   one project must never be served another project's completion.

A hit still writes a ledger row (`cache_hit=true`, cost 0) — usage accounting must show
the call happened, otherwise the ledger under-reports activity.
"""

import datetime
import hashlib
import json
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from osaip_api.models import LlmCache
from osaip_mesh.providers.base import CompletionRequest, Message

# Caching a moderation verdict or an eval run would hide exactly the variation those
# purposes exist to measure (ADR-0008 §4).
NON_CACHEABLE_PURPOSES = frozenset({"guardrail", "eval"})


def compute_request_hash(
    *,
    connection_id: uuid.UUID | None,
    project_id: uuid.UUID | None,
    request: CompletionRequest,
    redacted_messages: list[Message],
) -> str:
    """Canonical-JSON sha256 over everything that can change the answer. Same encoding
    discipline as the audit chain: sorted keys, compact separators, no NaN."""
    payload = {
        "connection_id": str(connection_id) if connection_id else None,
        "project_id": str(project_id) if project_id else None,
        "model": request.model,
        "max_tokens": request.max_tokens,
        # Serialized as a string so 0.0 and 0 cannot hash differently.
        "temperature": f"{request.temperature:.4f}",
        "messages": [{"role": m.role, "content": m.content} for m in redacted_messages],
    }
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass
class CachedResponse:
    content: str
    tokens_in: int
    tokens_out: int
    model_version: str | None
    # Carried through so a hit on an estimated count is not reported as exact.
    tokens_estimated: bool = False


def is_cacheable(*, ttl_s: int, purpose: str, temperature: float) -> bool:
    """A cache is only sound for deterministic requests. Above temperature 0 the
    caller asked for variation, so serving a stored answer would be wrong."""
    if ttl_s <= 0 or purpose in NON_CACHEABLE_PURPOSES:
        return False
    return temperature == 0.0


async def cache_lookup(session: AsyncSession, request_hash: str) -> CachedResponse | None:
    """Expiry is enforced in the query, not by the sweeper — a late sweep must never
    hand back a stale answer."""
    now = datetime.datetime.now(datetime.UTC)
    row = (
        await session.execute(
            select(LlmCache).where(LlmCache.request_hash == request_hash, LlmCache.expires_at > now)
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    stored: dict[str, Any] = row.response_json
    content = stored.get("content")
    if not isinstance(content, str):
        return None  # unreadable entry: treat as a miss rather than fail the call
    version = stored.get("model_version")
    return CachedResponse(
        content=content,
        tokens_in=row.tokens_in,
        tokens_out=row.tokens_out,
        model_version=version if isinstance(version, str) else None,
        tokens_estimated=bool(stored.get("tokens_estimated", False)),
    )


async def cache_store(
    session: AsyncSession,
    *,
    request_hash: str,
    connection_id: uuid.UUID | None,
    project_id: uuid.UUID | None,
    content: str,
    tokens_in: int,
    tokens_out: int,
    model_version: str | None,
    ttl_s: int,
    tokens_estimated: bool = False,
) -> None:
    expires_at = datetime.datetime.now(datetime.UTC) + datetime.timedelta(seconds=ttl_s)
    response_json: dict[str, Any] = {
        "content": content,
        "model_version": model_version,
        "tokens_estimated": tokens_estimated,
    }
    statement = pg_insert(LlmCache).values(
        request_hash=request_hash,
        connection_id=connection_id,
        project_id=project_id,
        response_json=response_json,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        expires_at=expires_at,
    )
    # Concurrent identical requests race here; last write wins and refreshes the TTL.
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=[LlmCache.request_hash],
            set_={
                "response_json": response_json,
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
                "expires_at": expires_at,
            },
        )
    )


# Expiry is a read-side rule (see `cache_lookup`), so reclaiming expired rows is pure
# housekeeping and lives with the worker's other retention sweeps, not here.
