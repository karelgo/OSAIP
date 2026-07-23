"""Postgres connectivity checks (async, driver-level — no SQL from user input here).

Field validation lives in `osaip_engine.safety`; this module assumes validated
inputs and maps driver failures to typed sanitized errors (ADR-0006 §4).
"""

import time
from dataclasses import dataclass

import asyncpg

from osaip_engine.errors import AuthFailed, DatabaseNotFound, HostUnreachable

CONNECT_TIMEOUT_S = 5.0


@dataclass
class PgTarget:
    host: str
    port: int
    database: str
    user: str
    password: str


async def test_connection(target: PgTarget) -> float:
    """Connect + SELECT 1. Returns latency in ms; raises typed engine errors."""
    started = time.perf_counter()
    try:
        conn = await asyncpg.connect(
            host=target.host,
            port=target.port,
            database=target.database,
            user=target.user,
            password=target.password,
            timeout=CONNECT_TIMEOUT_S,
        )
    except asyncpg.InvalidPasswordError as exc:
        raise AuthFailed() from exc
    except asyncpg.InvalidAuthorizationSpecificationError as exc:
        raise AuthFailed() from exc
    except asyncpg.InvalidCatalogNameError as exc:
        raise DatabaseNotFound() from exc
    except (TimeoutError, OSError) as exc:
        raise HostUnreachable() from exc
    try:
        await conn.fetchval("SELECT 1")
    finally:
        await conn.close()
    return (time.perf_counter() - started) * 1000
