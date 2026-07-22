# ADR-0002: asyncpg as the Postgres driver (not psycopg)

Status: Accepted · 2026-07-22 · Phase 0

## Context
Spec §3.1 (LOCKED) allows only Apache-2.0/MIT/BSD/PSF/PostgreSQL licenses for
in-process dependencies. The de-facto default driver, psycopg (2 and 3), is
**LGPL-3.0** — not on the allowlist. SQLAlchemy 2 async supports multiple drivers.

## Decision
Use **asyncpg (Apache-2.0)** as the sole Postgres driver, via SQLAlchemy 2 async
(`postgresql+asyncpg://`). Alembic runs migrations through the async engine
(`run_sync`). All app/worker/test code uses the async stack; testcontainers pytest
fixtures use the same URL scheme.

## Consequences
License policy holds without exceptions for the driver. asyncpg is faster for our
usage but has a few dialect quirks (e.g. server-side prepared statements with
pgbouncer, JSON codecs) — none affect Phase 0; revisit if a pooler is introduced.
LISTEN/NOTIFY for the SSE bus uses a dedicated raw asyncpg connection per process,
which asyncpg supports natively (`add_listener`).
