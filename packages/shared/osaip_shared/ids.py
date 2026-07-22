"""UUIDv7 generation — the single id source for app code, seeds, and data migrations.

UUIDv7 ids are identifiers, NEVER ordering keys: they are only monotonic within one
process. Anything that needs a total order (audit chain, SSE cursor) uses a dedicated
sequence column instead (see ADR-0003 / ADR-0005).
"""

import uuid
from typing import cast

import uuid6  # ships no type stubs; narrowed here so callers stay strictly typed


def new_id() -> uuid.UUID:
    """Return a new UUIDv7."""
    return cast(uuid.UUID, uuid6.uuid7())
