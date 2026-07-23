# ADR-0007: Jobs framework, recipe execution, and the Python sandbox

Status: Accepted · 2026-07-23 · Phase 2

Phase 2 adds the transformation layer: recipes compiled to DuckDB, a Postgres-backed
job queue that builds them, and a sandbox for user Python. This ADR records the
decisions a 4-lens adversarial review of the phase plan surfaced.

## 1. Job queue & JobExecutor

- **Postgres queue, job-grain claim.** The worker claims whole jobs, never
  individual steps: `SELECT ... FROM jobs WHERE status='queued' FOR UPDATE SKIP
  LOCKED LIMIT 1`, then commits `running`+`started_at`+`heartbeat_at` immediately.
  Claiming steps independently would let two workers interleave a job's steps and
  race the shared version flip. The `FOR UPDATE` row lock is released at that commit
  (a build runs for minutes; you cannot hold a row lock that long) — so post-claim
  concurrency is guarded by `status` + `heartbeat_at`, not the lock.
- **JobExecutor protocol.** The claim loop delegates step execution to a
  `JobExecutor` protocol with one in-process implementation in v1. External
  executors (Kestra/Dagster, spec §3.2/§7 Phase 13) slot in behind it.
- **Heartbeat + requeue.** A heartbeat coroutine bumps `jobs.heartbeat_at` every N
  seconds *concurrently* with the step. A sweeper requeues jobs where
  `status='running' AND heartbeat_at < now()-timeout`, incrementing `attempts`
  (capped → `failed`, so a poison job can't loop forever). The requeue timeout is
  comfortably larger than the heartbeat interval.
- **The worker must never block its own loop.** Every DuckDB/engine call in the
  worker goes through `osaip_engine.aio.run_engine` (thread offload) — exactly like
  the API. If a build step ran `duckdb.execute()` on the event loop, the heartbeat
  coroutine would stall, the sweeper would fire, and the same build would run twice
  (double S3 write + double version flip).
- **Cancel** is a flag row polled by a worker coroutine that calls
  `connection.interrupt()` on the live step connection and marks the job `cancelled`
  + downstream steps `skipped`. Between-steps checking alone cannot stop a long step.
- **Idempotent builds.** `POST /builds` honors `Idempotency-Key` and coalesces a
  target that already has a queued/running step (returns the existing job). The
  write+flip is wrapped in a per-dataset `pg_advisory_xact_lock` and no-ops if the
  job already finished.

## 2. Staleness & config hashing

A produced dataset is stale iff `producer.config_hash != version.recipe_config_hash`
OR any input's `current_version > version.input_versions[input]`; never-built if
`current_version = 0`. `config_hash` is computed in Python from the validated
pydantic model — `sha256(json.dumps(model_dump, sort_keys=True,
separators=(',',':'), ensure_ascii=False))` — and **never** from a `jsonb`
read-back: jsonb does not preserve key order and may normalize numbers, so a
round-trip would change the bytes and flip staleness with no config change. A
round-trip stability test guards this.

## 3. Reconstructability (Awb / AI Act Art 12)

Recipes are mutated in place (PATCH overwrites `config`). To keep the exact
transformation that produced a dataset version reconstructible, each
`dataset_versions` row stores `config_snapshot` (the full recipe config at build
time), and recipe mutations write the full before/after config to the audit log.

## 4. Recipe execution & the SQL validator

Visual recipes compile through **Ibis** to DuckDB, entering DuckDB exclusively via
`duck._connect(...)` + `ibis.duckdb.from_connection` so the P1 hardening
(autoload off, pinned extension dir, memory/thread caps) carries. Inputs register as
views aliased by ordinal (`in_1`, `in_2`) — DuckDB identifiers are case-insensitive,
so datasets `Sales`/`sales` would otherwise collide.

**SQL recipes** are defense-in-depth (a tables-only allowlist is exploitable —
`SELECT * FROM duckdb_secrets()` and `read_parquet('s3://…')` bypass it and leak
credentials):
1. **Allowlist validator** — sqlglot parse (duckdb dialect, RAISE); require exactly
   one `exp.Select`; every `exp.Table` must have empty catalog, db ∈ {'',main,memory},
   name ∈ registered input aliases (reject quoted-string tables = file paths); walk
   every function node and reject any not in a tiny scalar allowlist — explicitly
   forbid `duckdb_secrets`, `which_secret`, `read_*`, `glob`, `getenv`, `pragma_*`,
   `sniff_csv`.
2. **Secret-less execution** — SQL recipes run on a DuckDB connection with **no**
   S3/Postgres secrets registered; inputs are bound via worker-resolved
   `read_parquet` of the v<N> paths. A validator miss still leaks nothing.

The **expression language** (formula/filter/split) is a strict `ast` node whitelist
(no `eval`/`exec`, CI grep-gated): chained comparisons expand to AND-pairs (never
drop the second bound), division/modulo denominators are wrapped in `nullif(d,0)`
(no `inf`, no crash), and `col("name")` addresses non-identifier columns.

## 5. Python sandbox (spec §3.2/§10 LOCKED: "subprocess + limits, no network")

- **Baseline venv.** A pinned uv-managed venv (`osaip` SDK + pyarrow) provides the
  interpreter; P9's per-project uv envs replace it behind the same seam. The worker
  launches `<venv>/bin/python -I` with a **minimal** env — `HOME`+`TMPDIR`=job
  tempdir, `PATH`=venv/bin, `OSAIP_IO_MANIFEST` — asserted free of `OSAIP_`/`AWS_`
  (no ambient credentials). Truly empty env breaks common libs that read `~/.cache`;
  no secret ever enters it.
- **Limits.** In `preexec_fn` each `setrlimit` is wrapped in its own try/except:
  RLIMIT_AS is unsettable on macOS and would otherwise abort *every* launch. CPU +
  FSIZE apply everywhere (they work on macOS); AS applies on Linux only. A worker
  wall-clock kill is the cross-platform memory backstop.
- **No network** (this is LOCKED v1, not a deferred container feature): the
  subprocess is wrapped in `unshare -n` on Linux (network namespace with no
  interfaces). On macOS dev this is degraded-and-documented — the same posture the
  RLIMITs already take.
- **Compensating control (BIO2 8.12).** Until container isolation lands, a Python
  recipe whose inputs carry `bsn`/`bijzonder`/`bbn3` labels is blocked with an
  explained error + audit event — an un-isolated code path must not read
  special-category data over a channel whose egress isn't yet controlled.

## 6. Job logs

S3 has no append and `Storage` had no ranged GET, so step logs are written as
immutable chunk objects (`.../jobs/<job>/step-<n>/chunk-<k>.log`) and tailed via a
new `Storage.get_range` + a `?after=` offset endpoint. Only low-frequency
`job.updated`/`step.updated` events (plus a tiny `step.log` pointer = ordinal + new
byte offset, never content) go through the events table, each in its **own short
transaction** — publishing inside the step's work transaction would hold the
`osaip_events` advisory lock for the whole build and serialize every platform
mutation. The run drawer pulls log content from the log endpoint. Logs are a
personal-data-bearing stream: they inherit the max input classification, get an
interim 30-day TTL prune (CP-3 retention when it lands), and error paths are
sanitized like preview errors. The SSE-7-day vs S3-30-day asymmetry is intentional.

## 7. CP-1 / CP-2 propagation at build

- **CP-1** output labels are a **floor** = MAX(input labels). Rebuild re-applies the
  floor; a manual raise persists; lowering below the floor requires an audit reason
  (ratchet — propagate-through-lineage must not be silently defeated). Column labels
  carry through by identity for select/rename/stack/split/sample and non-collision
  join columns; derived columns (formula/agg/SQL/Python) inherit the MAX of their
  source columns as an interim rule (precise derived-column labeling is deferred).
- **CP-2** output `purpose_codes` = **INTERSECTION** of input purposes (doelbinding /
  Art 5(1)(b) — union would make joined data usable for a purpose neither source
  permitted). `legal_basis` is recorded as the provenance union; an empty
  intersection flags the output for human reconciliation. Recipe-level purpose
  *declaration* (the `recipes.purpose_codes` column) ships now; the
  compatibility-*enforcement* engine is deferred to Phase 6 (with tools).

## 8. Worker → osaip_api import

The worker takes a workspace dependency on `osaip_api` for models/audit/events
(single source of truth over a premature models→shared refactor). **Concrete
refactor trigger:** before Phase 8 scenario steps land in the worker, move
models/audit/events into `packages/shared`. Until then the coupling is one-way and
recorded.
