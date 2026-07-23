# Phase 1 — Connections & datasets

Status: **approved** (user, 2026-07-23). Includes [P1]-tagged Compliance Pack items
CP-1 (classification, tri-field) + CP-2 (purpose binding) in v1 form (COMPLIANCE_NL.md
§5). Draft was adversarially reviewed by 4 verifier agents (spec coverage, compliance,
codebase fit, feasibility); 4 blockers + 14 majors folded in.

**Spec AC (§7):** CSV upload → typed schema + profile · Postgres table registered →
preview · bad creds fail cleanly without leaking.

## Scope
1. **Secrets** (ADR-0006): `secrets` table, MultiFernet from day one
   (`OSAIP_SECRET_KEY` = comma-separated keys; rotation = prepend + lazy re-encrypt);
   startup key validation; write-only via API; `cryptography` direct dep.
2. **Connections** (kinds postgres | s3 | duckdb_file; uploads need no connection):
   CRUD + `test` + `inspect`. RBAC: **admin** manages connections incl. secrets;
   **editor** registers datasets on existing connections; viewer read-only. New
   capability `can_manage_connections`. CP-2 `legal_basis` + `purpose_codes[]`
   required. DELETE blocked while referenced → 409.
3. **Preview-first (§6.3(3))**: upload → `POST /uploads` stores raw to
   `projects/<key>/artifacts/uploads/<uuid>` (worker prunes >24h) and returns
   {upload_id, inferred schema, params, ~50-row preview}; user confirms →
   `POST /datasets {source:{kind:upload}}` builds typed parquet v1 + profile.
   Register: `POST /connections/{id}/inspect {table|path}` previews via READ_ONLY
   attach BEFORE `POST /datasets`.
4. **Storage interface** `packages/engine/osaip_engine/storage.py` (boto3; the one
   S3 path per §3.1; layout constants in shared): `projects/<key>/datasets/<name>/
   v<N>/part-0.parquet`; idempotent ensure_bucket. Settings gain `OSAIP_S3_ENDPOINT/
   BUCKET/ACCESS_KEY/SECRET_KEY/REGION/USE_SSL` (dev default localhost:8333; compose
   overrides seaweedfs:8333 — same dual-hostname pattern as OIDC). SeaweedFS gets an
   `-s3.config` identity file (real dev creds) + api `depends_on` it healthy.
5. **Engine** (`duck.py`): per-call in-memory DuckDB, `memory_limit`/`threads` capped,
   `autoinstall/autoload=false` + explicit LOAD from env-pinned `extension_directory`
   (baked in Docker after final uv sync); **duckdb pinned exact** (ADR-0006 exception
   to `>=`); S3 via `CREATE SECRET (TYPE s3, ENDPOINT scheme-less, URL_STYLE path…)`
   from the same config boto3 uses. **All engine/boto3 calls off the event loop**
   (anyio.to_thread + bounded semaphore 3; timeout = watchdog `conn.interrupt()`).
   xlsx via DuckDB excel extension (25 MB cap + row/col bounds; calamine fallback
   recorded). Profile = explicit SQL aggregates (never SUMMARIZE — unstable shape).
   Engine raises typed sanitized exceptions; api translates to problem+json.
6. **Injection/confinement (§8)**: postgres attach ALWAYS READ_ONLY (INSERT-fails
   test; note: modern postgres ext CAN write); creds via `CREATE SECRET (TYPE
   postgres, …)` per-field with tested `sql_literal()`, never conninfo strings; field
   validation (host regex, port int, db/user `^[A-Za-z0-9_.$-]+$`); identifiers via
   tested `sql_ident()`; duckdb_file/s3 paths canonicalized + contained under
   `projects/<key>/`, attached READ_ONLY; parquet uploads validated by full DuckDB
   read; SSRF: dev denies platform DB host, risk recorded. Upload cap: early 413 on
   Content-Length + byte-counting ASGI guard (aborts before multipart spools);
   100 MB csv/parquet, 25 MB xlsx.
7. **Datasets** (migration 0002): CP-1 tri-field labels on dataset AND columns —
   `classification (none|persoonsgegevens|bijzonder|bsn)` + orthogonal `bbn_level`
   + `confidentiality` (all five compliance dimensions; no enum shoehorn). CP-2
   fields on datasets too (inherit connection defaults). `params jsonb` records
   inference decisions (dataset = schema + location + **params**, §1). row_count
   exact for parquet; reltuples estimate ("~") or null for external (exact = P2 job).
   SSE topic `datasets`; ObjectRef upsert helper (ON CONFLICT — the Phase-0 fake
   seed ref collides otherwise). DELETE = archive.
8. **Sample + ETag**: parquet versions → `W/"<id>:v<N>:<limit>"` checked BEFORE
   engine work (304 = zero DuckDB); external kinds → no-cache, no ETag. Row
   serialization policy (datetime→ISO, Decimal→str) lives in engine.
9. **Frontend**: datasets list (badges, kinds, rows; row click navigates — the
   §6.3(2) inspector arrives with the P2 canvas; recorded deviation, tabs become
   inspector content then); upload preview/confirm flow (determinate progress = P1
   run affordance; job drawer P2 — recorded for upload AND profile recompute);
   register panel w/ live preview; dataset page Schema · Sample · Profile +
   Configure (labels, CP fields); settings gains Connections tab + `?tab=` URL sync
   (order General · Members · Connections · Audit). Unwiring: nav phase marker,
   router STUBS, datasetDetailRoute, checklist caption. SSE: addEventListener AND
   invalidate case (named events skip onmessage). @tanstack/react-table; bundle
   budget checked, lazy-route if tight.
10. **Seed v2**: per-resource idempotent ensures (old early-return never upgraded
    Phase-0 DBs): real `sales_orders` (bundled CSV → parquet via engine; upsert
    replaces fake ref), `demo_src` PG database + `sales` table (AUTOCOMMIT create,
    duplicate-tolerant). Double-run pytest over a Phase-0-seeded DB.
11. **Wiring**: osaip-engine deps (duckdb pin, pyarrow, boto3) + api workspace dep +
    compose volume mounts for engine + Makefile/CI mypy + ruff first-party +
    boto3/duckdb/pyarrow mypy overrides + seaweedfs in e2e/CI boot lists. Mutation
    order everywhere: mutate → publish_event/notify → **write_audit LAST** → commit.
    Upload endpoint exempt from idempotency keys (multipart; P2 jobs make uploads
    restartable — recorded).

Out of scope (recorded): jobs/async + exact external counts + run drawer (P2) ·
CP-1 lineage/exports/tools propagation (P2+; column labels already in schema_json) ·
CP-2 query-time enforcement, person-lookup query reasons + consultation reports
(P7-ish; sample access is audit-logged meanwhile), recertification (P7) · raw-upload
retention beyond 24h prune · xlsx multi-sheet UI (sheet in params) · dlt (P13).

## Endpoints (`/api/v1`; problem+json, audit; RBAC above)
`GET|POST /projects/{key}/connections` · `GET|PATCH|DELETE .../connections/{id}` ·
`POST .../connections/{id}/test` → {ok, latency_ms}|sanitized problem ·
`POST .../connections/{id}/inspect` {table|path} → {schema, preview} ·
`POST /projects/{key}/uploads` (multipart, 413-guarded) → {upload_id, schema, params,
preview} · `POST /projects/{key}/datasets` (upload_id | connection source; CP fields
required) · `GET /projects/{key}/datasets` (cursor, ETag) · `GET|PATCH|DELETE
.../datasets/{name}` · `GET .../datasets/{name}/sample?limit=` ·
`POST .../datasets/{name}/profile`

## Schema (0002_connections_datasets)
secrets(project_id, name, ciphertext, key_id?) ·
connections(project_id, name uq/proj, kind ck, config jsonb, secret_id?, legal_basis,
purpose_codes[], status, created_by) ·
datasets(project_id, name uq/proj, kind file|table|s3|duckdb_file, connection_id?,
description, classification ck, bbn_level ck?, confidentiality ck?, legal_basis,
purpose_codes[], params jsonb, status, current_version, created_by) ·
dataset_versions(dataset_id, version, location, format parquet|external, schema_json,
row_count?, row_count_kind?, profile_json?; uq(dataset_id, version))

## Test list
**pytest**: secrets round-trip/rotation/startup-validation; connections RBAC
(admin-only; editor+viewer 403) + CP-2 required; test-connection good/bad vs
testcontainer PG AND s3 bad-creds vs SeaweedFS testcontainer — bodies secret-free
(AC-3, both kinds); attach READ_ONLY (INSERT fails); malicious identifier + `..`
path rejected; upload csv/parquet/xlsx → typed schema; empty/oversize/bad-ext/
xlsx-bomb rejected; 413 aborts mid-stream; preview-before-create; corrupt parquet
rejected; s3-path + duckdb_file register → sample; profile fixture values incl.
datetime/Decimal; ETag 304 without engine call (spy) + external no-store; warm
sample < 1 s (CI-generous; §6.5 300 ms local target); seed double-run; audit per
mutation + ordering; events. **Playwright**: 11-upload-csv (AC-1 full preview→
confirm→schema+profile) · 12-postgres-dataset (AC-2 as admin; host=postgres:5432 —
container-dialed) · 13-bad-creds (AC-3) · axe on all new pages.

## New dependencies (§3.1 — all allowlisted)
duckdb MIT (exact pin) · pyarrow Apache-2.0 · boto3 Apache-2.0 · python-multipart
Apache-2.0 · cryptography Apache-2.0/BSD (direct) · @tanstack/react-table MIT.

## Risks
Blocking C code on event loop → thread offload + semaphore + interrupt watchdog.
SeaweedFS quirks → e2e COPY TO s3:// write test; interface isolates. Extension
drift → exact pin + autoload off. xlsx fidelity → fixtures + calamine fallback.
Injection → dedicated sql_literal/sql_ident tests. Preview latency → budget test.

## Slices
0 docs+ADR-0006 · 1 secrets+0002+connections API · 2 engine+storage+uploads+S3
wiring · 3 inspect/register+datasets API+seed v2 · 4 frontend · 5 e2e+CI+docs.

## Definition of done
`make dev` clean; `make seed` idempotent (real dataset + demo_src); `make ci` green
incl. specs 11-13; §6.7 checklist on all new screens; bad-creds bodies secret-free
(pg + s3); attach write-blocked; summary + stop (§9.4).
