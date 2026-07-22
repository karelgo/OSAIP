# ADR-0003: SSE event bus — events table with seq cursor, NOTIFY as wake-up

Status: Accepted · 2026-07-22 · Phase 0

## Context
Spec §6.6 locks one multiplexed `GET /events` SSE channel backed by Postgres
LISTEN/NOTIFY driving TanStack Query invalidation. Naive designs have three failure
modes: NOTIFY payloads are capped at 8KB; UUID/timestamp cursors are incoherent because
NOTIFY delivers in commit order while ids are assigned at insert (a smaller id can
commit later and be skipped forever by `WHERE id > last`); and replay vs live delivery
through two code paths drifts.

## Decision
- `events(id uuidv7, seq BIGSERIAL, ts, topic, project_id?, user_id?, type,
  payload_json)`. **`seq` is the SSE `id:` and the only cursor.** UUIDv7 ids are
  identifiers, never ordering keys.
- Publishing = INSERT under a short `pg_advisory_xact_lock` (serializes seq order with
  commit order; event volume in v1 is trivial) + `pg_notify('osaip_events', '')`.
  **NOTIFY is a pure wake-up with an empty payload** — the 8KB limit is moot.
- Each api process holds ONE dedicated non-pooled asyncpg LISTEN connection fanning
  into per-client bounded asyncio queues. Overflow ⇒ disconnect that client; it
  reconnects with `Last-Event-ID`.
- Every wake-up AND every reconnect run the same read: `WHERE seq > cursor ORDER BY
  seq`, filtered by a single `event_visible(user, event)` predicate (project membership
  cached ~10s; user-targeted events only to that user). One code path for live + replay.
- The worker prunes events older than 7 days. A `Last-Event-ID` older than retention
  gets a `reset` control event: the client invalidates all queries and resumes from head.
- 15-second heartbeat comments keep intermediaries from timing out; the dev proxy is
  configured with buffering off (e2e runs against built output, not the dev proxy).

## Consequences
Exactly-once-per-cursor delivery without a broker; replay is correct under concurrent
commits; permission filtering is single-sourced. Cost: one LISTEN connection per
process and an advisory lock on the (low-volume) publish path. If event volume ever
makes the lock hot, move to a logical-clock column filled by a trigger.
