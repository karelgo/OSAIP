# ADR-0006: Secret handling, storage config split, and the DuckDB exact pin

Status: Accepted · 2026-07-23 · Phase 1

## 1. Secrets at rest (connections)

Connection credentials are stored in a dedicated `secrets` table as Fernet
ciphertext (`cryptography`, now a direct dependency), never in `connections.config`.

- **MultiFernet from day one.** `OSAIP_SECRET_KEY` accepts a comma-separated list of
  urlsafe-base64 32-byte keys. Encryption always uses the FIRST key; decryption tries
  all. Rotation = prepend a new key, re-encrypt lazily on next write (a `key_id`
  column records which key produced each ciphertext for auditability). Retrofitting
  MultiFernet after rows exist is the painful version — so it ships first.
- **Startup validation.** Keys are parsed at application startup; an invalid or
  missing key fails boot with a clear error — never at first secret write. The dev
  default is a valid, well-known key (dev-only; deployment checklist requires
  replacing it).
- **Write-only API.** Secret values are accepted on POST/PATCH and never serialized
  back in any response, log line, or audit detail. `decrypt` is never called with a
  TTL (connection secrets do not expire via Fernet).

## 2. Storage configuration (dual-hostname, like OIDC)

All S3 access goes through one interface: `packages/engine/osaip_engine/storage.py`
(engine owns I/O adapters per §3.3; path-layout constants live in `osaip_shared`).
Settings: `OSAIP_S3_ENDPOINT / BUCKET / ACCESS_KEY / SECRET_KEY / REGION / USE_SSL`.
Host-run tools (seed, pytest) default to `localhost:8333`; containers override to
`seaweedfs:8333` via the compose env anchor — the same split ADR-0001 uses for OIDC.
SeaweedFS runs with an `-s3.config` identity file so dev has real, testable
credentials; buckets are created idempotently (`ensure_bucket`) — SeaweedFS does not
auto-create them. DuckDB's S3 access (`CREATE SECRET (TYPE s3, ENDPOINT 'host:port'
— scheme-less, URL_STYLE 'path', USE_SSL, REGION, KEY_ID, SECRET)`) is built from
the SAME settings object, so boto3 and DuckDB can never diverge.

## 3. DuckDB exact pin (recorded exception)

The repo convention is `>=` minimums. `duckdb` is pinned **exact** instead:
extension ABI, inference behavior, and profile output all drift across DuckDB
releases, and extensions install per-version. Extensions (httpfs, postgres, excel)
are installed at Docker build into an env-pinned `extension_directory`
(HOME/user-independent), and runtime connections set
`autoinstall_known_extensions=false; autoload_known_extensions=false` with explicit
`LOAD`s — a missing extension fails loudly in CI instead of silently downloading.
Upgrades are deliberate: bump the pin, rebake, rerun the profile fixtures.

## 4. Engine execution model

DuckDB and boto3 are blocking C/network code inside an async app: every engine call
runs via `anyio.to_thread.run_sync` behind a bounded semaphore (default 3), each
connection capped (`SET memory_limit`, `SET threads`), and timeouts are enforced by
a watchdog calling `connection.interrupt()` (the only supported cancellation).
The engine raises typed, sanitized exceptions (auth failed / host unreachable /
database not found / interrupted); the API layer translates them to problem+json.
Raw driver messages (which may embed DSNs) never reach responses — asserted by test.
