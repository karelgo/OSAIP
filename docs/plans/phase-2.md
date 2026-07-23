# Phase 2 — Flow & recipes v1

Status: **approved** (user, 2026-07-23). Establishes the canonical §6.3 inspector +
run-drawer patterns every later module reuses; reference path §5a. Draft was
adversarially reviewed by 4 verifier agents (spec/compliance/codebase/feasibility);
4 blockers + ~20 majors folded in. Decisions in ADR-0007.

**Spec AC (e2e):** CSV → prepare → join(Postgres) → group builds; mid-flow edit
rebuilds only stale.

## Scope
1. **Migration 0003**: recipes (kind, config jsonb, config_hash, purpose_codes,
   status) · recipe_inputs · recipe_outputs (dataset_id uq GLOBAL = single producer)
   · jobs (status, trigger ck, heartbeat_at, claimed_by, attempts) · job_steps
   (status, log_prefix, error) · dataset_versions +recipe_config_hash/input_versions/
   config_snapshot. Recipe mutations write before/after config to audit.
2. **Staleness/hash** (ADR-0007 §2): STALE iff producer.config_hash≠version hash OR
   input current_version>recorded; config_hash from the pydantic model in Python
   (sort_keys, compact, ensure_ascii=False), never jsonb round-trip.
3. **Recipes API**: CRUD + save validation (inputs active; output name regex; adopt
   producer-less dataset else 409; single-producer 409; cycle DFS 422); `POST
   .../recipes/{id}/preview {config?,limit}` accepts a DRAFT config (never persists/
   writes, §6.3(3)), ≤15s interrupt, non-finite→null (Python recipes: no live
   preview, recorded); `GET /flow` VM (ETag; datasets+status, recipes, edges, caps);
   object_refs upsert on recipe CRUD + ⌘K "Build <dataset>"/"Open recipe"; patch P1
   datasets archive-guard 409 when referenced by an active recipe.
4. **Visual recipes** (pydantic in shared; `osaip_engine/recipes.py` Ibis→DuckDB via
   `duck._connect`+`from_connection`): prepare (rename/cast/filter/formula/fill_nulls/
   dedupe/**select-cols**), join, group, stack, split, sample (seeded). Inputs
   aliased `in_1`/`in_2` (case-insensitive-collision safe).
5. **Expressions** (`osaip_engine/expressions.py`): ast whitelist, chained-comparison
   expansion, nullif div/mod guard, col()+function allowlist, no eval/exec (grep-gate).
6. **SQL recipe** (ADR-0007 §4): sqlglot allowlist (single Select, tables⊆inputs,
   function allowlist forbidding duckdb_secrets/read_*/glob/getenv/pragma_*) + exec on
   a SECRET-LESS connection (inputs via worker-resolved read_parquet).
7. **Python recipe** (ADR-0007 §5): pinned baseline venv, `python -I` minimal env (no
   OSAIP_/AWS_), per-setrlimit try/except (CPU+FSIZE all, AS linux), `unshare -n`
   no-network (linux; degraded macOS), wall-clock kill; osaip SDK input/output;
   output parquet validated→v<N>; BSN/bijzonder/bbn3 input gate + audit.
8. **Jobs** (ADR-0007 §1, JobExecutor protocol): SKIP LOCKED job-grain claim,
   immediate running commit, heartbeat + cancel-poll coroutines concurrent with
   run_engine-offloaded step, requeue sweeper (attempts cap); POST /builds
   idempotency-key + coalesce + per-dataset advisory lock; cancel→interrupt+skip;
   failure→downstream skipped.
9. **Atomic write + §5a** (ADR-0007): delete-prefix retry→ibis to_parquet→txn insert
   version (schema+row_count+refreshed profile+config_snapshot+hashes)+flip+CP-1
   floor/CP-2 intersection+object_ref, no-op if job finished; orphan sweeper in prune
   loop.
10. **Logs** (ADR-0007 §6): S3 chunk objects + Storage.get_range + ?after= tail;
    low-freq job/step SSE events (tiny step.log pointer) in own txns; 30d prune;
    sanitized step errors; MAX-input classification.
11. **Canvas** (`packages/canvas`): @xyflow/react, sync dagre behind a stable iface,
    node anatomy §6.3(1) + status ring + classification badges, living-Flow edge
    pulses (reduced-motion).
12. **Flow page** at /p/$key: empty-graph = onboarding checklist (keeps
    project-home/onboarding-checklist testids) + §6.3(9) templates; URL selection
    ?sel/?tab/?job (restore-tested); canonical inspector **Configure·Preview·Runs·
    Lineage·Docs** (forms defaults-first+Advanced §6.3(10); Monaco lazy self-hosted);
    run drawer (§6.3(4)) step timeline + live log tail + toast deep-links; keyboard
    canvas nav §6.4; dataset page Lineage tab.
13. **Jobs web**: /p/$key/jobs list+detail (reuse run-drawer); remove jobs STUBS +
    phase:2 nav markers.
14. **Bundle**: React.lazy Flow feature (initial route) + nested Monaco boundary.
15. **Seed v2.1**: demo_src connection+secret (Vault, host postgres:5432) + prebuilt
    `sales_enriched` recipe so the Flow renders alive.
16. **Wiring**: worker gains osaip-api dep + compose mount + depends_on api healthy;
    gen-api+commit client+spectral in every API slice (1,3); OSAIP_ENGINE_CONCURRENCY;
    separate preview/build DuckDB memory limits + build temp_directory.

Out of scope (recorded): scenarios/triggers (P8; enum reserved) · metrics&checks UI +
Pandera + gating (P8; per-build stats ARE in §5a) · charts (P12) · Trino/Spark (P13,
seams ready) · container net/fs isolation (v1 = unshare-n + rlimits + BSN gate) ·
CP-2 compatibility enforcement engine (declaration + intersection now; blocking →P6) ·
precise derived-column CP-1 labels (interim MAX now) · recipe dup/multiselect (P2.x) ·
SQL over arbitrary connections (datasets only; sql_query tool P6).

## Endpoints (`/api/v1`; editor+ mutates, viewer reads)
`GET|POST /projects/{key}/recipes` · `GET|PATCH|DELETE .../recipes/{id}` ·
`POST .../recipes/{id}/preview {config?,limit}` · `GET /projects/{key}/flow` ·
`POST /projects/{key}/builds {targets[],force?}` (idempotency-key) ·
`GET /projects/{key}/jobs` · `GET .../jobs/{id}` ·
`GET .../jobs/{id}/steps/{ordinal}/log?after=` · `POST .../jobs/{id}/cancel`

## Schema (0003)
recipes(project_id, name uq/proj, kind ck, config jsonb, config_hash, purpose_codes[],
status, created_by) · recipe_inputs(recipe_id, dataset_id, ordinal) ·
recipe_outputs(recipe_id, dataset_id uq, ordinal) · jobs(project_id, kind, status ck,
trigger ck, requested_by, heartbeat_at, claimed_by, attempts, created/started/
finished) · job_steps(job_id, ordinal, recipe_id, target_dataset_id, status ck,
started/finished, log_prefix, error) · dataset_versions +recipe_config_hash?
+input_versions jsonb? +config_snapshot jsonb?

## Test list
**engine**: expression matrix + hostile rejects, chained-comparison bound, div/mod-by-
zero→null; each visual recipe value-asserted (select-cols, hyphen names, seeded
determinism threads=2); SQL validator (duckdb_secrets/read_parquet-s3/read_csv-etc/
glob/getenv/information_schema/quoted-table rejected; secret-less exec can't read
creds; joins+CTE-SELECT accepted); sandbox (env no OSAIP_/AWS_, host-OS launch guard,
CPU-kill linux, unshare-n blocks egress linux, oversized reject, BSN block).
**api**: recipes CRUD/RBAC/audit(before-after)/events; single-producer 409; cycle 422;
draft-config preview returns rows + no version bump; flow VM transitions; build
resolution (full/stale-subset/force/postgres); idempotent builds (2→1 bump);
config_hash round-trip; CP-1 floor/ratchet + CP-2 intersection; archive-guard 409.
**worker**: no double-claim (SKIP LOCKED); heartbeat requeue (no double flip); step
failure→downstream skipped; S3 chunk logs + get_range tail; atomic crash leaves old
version + orphan swept; cancel interrupts live step.
**e2e**: 14-flow-build (AC-1) · 15-stale-rebuild (AC-2, exactly 2 steps) · URL restore
· empty-Flow starting point · ⌘K build → drawer · inspector keyboard/canvas-arrows ·
error/skeleton/empty on flow+jobs · axe · visual smoke.

## New deps (§3.1)
ibis-framework[duckdb]==12.* Apache-2.0 + sqlglot==30.* MIT (pinned; ibis bound
floats) + transitives (pandas/numpy BSD, pyarrow/pyarrow-hotfix/tzdata/packaging
Apache, rich/atpublic/parsy MIT, python-dateutil Apache/BSD, toolz BSD) · @xyflow/
react, @dagrejs/dagre, monaco-editor, @monaco-editor/react MIT. License gate updated
slice 2.

## Slices
0 docs+ADR-0007 · 1 migration 0003+recipes CRUD+flow VM+object_refs/⌘K+datasets
archive-guard · 2 engine expressions+compilers+SQL validator+preview+deps · 3 jobs
queue+executor+build+atomic write+logs/SSE+worker wiring · 4 python sandbox+SDK · 5
canvas+Flow+inspector+run drawer+jobs UI · 6 e2e 14/15+seed v2.1+CI+docs+summary.

## DoD
`make dev` clean; seed shows a live Flow; `make ci` green incl. both AC specs; §6.7 on
flow/inspector/run-drawer/jobs (skeleton/empty/error+retry/keyboard/dark/deep-link-
restore); preview <300ms local (CI 1s budget); no eval/exec in engine (grep-gate);
SQL-exfil + sandbox-env + no-network tests green; audit stores before/after config.
Summary + stop (§9.4).
