"""Idempotency-Key support for POSTs (§6.6).

Same user + key + identical payload → stored response is replayed. Same key with a
DIFFERENT payload → 422 (client bug). Rows are pruned after 24h by the worker.
"""

import hashlib
import json
from typing import Any

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from osaip_api.models import IdempotencyKey, User
from osaip_api.problem import Problem


def _request_hash(method_path: str, body: Any) -> str:
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(f"{method_path}\n{canonical}".encode()).hexdigest()


async def check_idempotency(
    session: AsyncSession, request: Request, user: User, body: Any
) -> tuple[str | None, str, tuple[int, Any] | None]:
    """Returns (key, request_hash, stored_response|None). key None ⇒ header absent."""
    key = request.headers.get("idempotency-key")
    method_path = f"{request.method} {request.url.path}"
    req_hash = _request_hash(method_path, body)
    if key is None:
        return None, req_hash, None
    row = (
        await session.execute(
            select(IdempotencyKey).where(
                IdempotencyKey.user_id == user.id, IdempotencyKey.key == key
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return key, req_hash, None
    if row.request_hash != req_hash:
        raise Problem(
            422,
            title="Idempotency key reused",
            detail="This Idempotency-Key was already used with a different request payload.",
            hint="Generate a fresh key for each distinct request.",
            slug="idempotency-key-reuse",
        )
    return key, req_hash, (row.response_status, row.response_body)


async def store_idempotent_response(
    session: AsyncSession,
    user: User,
    key: str,
    request: Request,
    req_hash: str,
    status: int,
    body: Any,
) -> None:
    session.add(
        IdempotencyKey(
            user_id=user.id,
            key=key,
            method_path=f"{request.method} {request.url.path}",
            request_hash=req_hash,
            response_status=status,
            response_body=body,
        )
    )
