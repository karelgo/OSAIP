"""Hash-chained append-only audit log (CP-7; contract in ADR-0005).

Canonicalization is RFC-8785-style JSON over values exactly as a DB read-back yields
them, so `verify_chain` recomputes byte-identical input from fresh rows:
- keys sorted, compact separators, ensure_ascii=False, NaN/Inf rejected
- ts: fixed-width UTC ISO-8601 with microseconds ("...+00:00")
- UUIDs as lowercase strings; ip as text; details restricted to JSON-safe values
  WITHOUT floats (jsonb round-trip safety)

`seq` (DB identity) is the chain order and is NOT part of the hash (it is unknowable
pre-insert); any reorder still breaks the prev_hash linkage and is detected.
"""

import datetime
import hashlib
import json
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from osaip_api.models import AuditLog
from osaip_shared.ids import new_id

GENESIS_HASH = "0" * 64
_AUDIT_LOCK_SQL = text("SELECT pg_advisory_xact_lock(hashtext('osaip_audit'))")


def _canonical_ts(ts: datetime.datetime) -> str:
    return ts.astimezone(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%S.%f+00:00")


def _check_details(value: Any, path: str = "details") -> None:
    """Reject floats (jsonb may re-render them) and non-JSON types."""
    if isinstance(value, bool) or value is None or isinstance(value, int | str):
        return
    if isinstance(value, float):
        raise ValueError(f"audit {path}: floats are not allowed (jsonb round-trip)")
    if isinstance(value, list):
        for i, item in enumerate(value):
            _check_details(item, f"{path}[{i}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"audit {path}: non-string key {key!r}")
            _check_details(item, f"{path}.{key}")
        return
    raise ValueError(f"audit {path}: unsupported type {type(value).__name__}")


def canonical_row(
    *,
    id: uuid.UUID,
    ts: datetime.datetime,
    actor_id: uuid.UUID | None,
    project_id: uuid.UUID | None,
    action: str,
    object_kind: str,
    object_id: str | None,
    details: dict[str, Any],
    ip: str | None,
) -> str:
    payload = {
        "id": str(id),
        "ts": _canonical_ts(ts),
        "actor_id": str(actor_id) if actor_id else None,
        "project_id": str(project_id) if project_id else None,
        "action": action,
        "object_kind": object_kind,
        "object_id": object_id,
        "details": details,
        "ip": ip,
    }
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def row_hash(prev_hash: str, canonical: str) -> str:
    return hashlib.sha256((prev_hash + canonical).encode("utf-8")).hexdigest()


async def write_audit(
    session: AsyncSession,
    *,
    actor_id: uuid.UUID | None,
    project_id: uuid.UUID | None,
    action: str,
    object_kind: str,
    object_id: str | None = None,
    details: dict[str, Any] | None = None,
    ip: str | None = None,
) -> AuditLog:
    """Append one chained row. MUST be the last write before the transaction commits:
    the advisory xact lock serializes chain writers until COMMIT (ADR-0005)."""
    details = details or {}
    _check_details(details)
    await session.execute(_AUDIT_LOCK_SQL)
    head = (
        await session.execute(select(AuditLog.row_hash).order_by(AuditLog.seq.desc()).limit(1))
    ).scalar_one_or_none()
    prev = head if head is not None else GENESIS_HASH

    entry = AuditLog(
        id=new_id(),
        ts=datetime.datetime.now(datetime.UTC),
        actor_id=actor_id,
        project_id=project_id,
        action=action,
        object_kind=object_kind,
        object_id=object_id,
        details=details,
        ip=ip,
        prev_hash=prev,
    )
    entry.row_hash = row_hash(
        prev,
        canonical_row(
            id=entry.id,
            ts=entry.ts,
            actor_id=actor_id,
            project_id=project_id,
            action=action,
            object_kind=object_kind,
            object_id=object_id,
            details=details,
            ip=ip,
        ),
    )
    session.add(entry)
    await session.flush()
    return entry


@dataclass
class VerifyResult:
    ok: bool
    checked: int
    first_bad_seq: int | None = None
    reason: str | None = None


async def verify_chain(session: AsyncSession, *, batch_size: int = 1000) -> VerifyResult:
    """Walk the chain by seq from fresh reads, in batches (keyset pagination)."""
    prev = GENESIS_HASH
    checked = 0
    last_seq = 0
    while True:
        rows = (
            (
                await session.execute(
                    select(AuditLog)
                    .where(AuditLog.seq > last_seq)
                    .order_by(AuditLog.seq)
                    .limit(batch_size)
                )
            )
            .scalars()
            .all()
        )
        if not rows:
            return VerifyResult(ok=True, checked=checked)
        for row in rows:
            if row.prev_hash != prev:
                return VerifyResult(
                    ok=False, checked=checked, first_bad_seq=row.seq, reason="prev_hash mismatch"
                )
            expected = row_hash(
                prev,
                canonical_row(
                    id=row.id,
                    ts=row.ts,
                    actor_id=row.actor_id,
                    project_id=row.project_id,
                    action=row.action,
                    object_kind=row.object_kind,
                    object_id=row.object_id,
                    details=row.details,
                    ip=row.ip,
                ),
            )
            if row.row_hash != expected:
                return VerifyResult(
                    ok=False, checked=checked, first_bad_seq=row.seq, reason="row_hash mismatch"
                )
            prev = row.row_hash
            last_seq = row.seq
            checked += 1
