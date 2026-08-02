# Changelog

All notable changes to OSAIP. Format loosely follows Keep a Changelog; the project is
pre-1.0, so minor versions may break.

## [0.4.0] — Phase 3a · LLM Mesh foundation (2026-08-02)

The gateway every model call passes through (spec §5b; decisions in ADR-0008/0009).
Phase 3 was split after a review returned 24 blockers: 3a is the foundation, 3b adds
LLM recipes and Prompt Studio.

### Added
- **`apps/mesh`**: internal-only service (service token, no published port) owning the
  call ORDER — CP-11 residency gate → guardrails `pre` (redact) → quota reserve →
  cache → provider → guardrails `post` → settle. Redaction runs BEFORE the cache and
  the provider; the literal §5b order would have defeated its own acceptance criterion
  (ADR-0008 §1).
- **Usage ledger** (§4) with full attribution — job/step/row, trace/span,
  provider/model/model_version, tokens, integer cost micros + currency, latency,
  cache_hit, status — plus traces/spans the P6 Trace Explorer will read.
- **Audit storage** per connection: `redacted` (default) leaves no raw copy, `full`
  keeps both, `off` stores no text but still ledgers the call.
- **Budgets** by reserve/settle: a committed hold is visible to concurrent callers, so
  parallel calls cannot collectively overshoot; stale holds are ignored on read.
  `block` → 429 `quota-exceeded`, distinct from a provider rate-limit.
- **`packages/guardrails`** (dependency-free): BSN 11-proef, IBAN mod-97, email, phone,
  including the grouped forms Dutch case files use. Events record counts, never values.
  The PII baseline cannot be configured away (BIO2 8.12). §5d `untrusted_block()`.
  Dutch NER via Presidio is opt-in and operator-installed.
- **CP-11 sovereignty gate** at the choke point: `bsn`/`bijzonder` may only reach a
  `local` connection; an undeclared classification fails closed. A refusal is a 403
  that says what to change, recorded in `guardrail_events` AND the chained audit.
  Residency is operator-asserted metadata, stated as such on every read.
- **Providers**: built-in `echo` (deterministic, free, refuses non-local residency) and
  a LiteLLM adapter (openai-compatible/anthropic/ollama) wrapped behind our own
  protocol, SSRF-guarded per call, with provider errors sanitised so neither the API
  key nor the prompt escapes.
- **API**: LLM connections (write-only keys, mandatory legal basis + purpose codes),
  quotas, usage rollups, append-only prompt versions, guardrail policies with their
  effective settings.
- **Web**: an LLM tab (connections + budgets) and a Usage panel, both deep-linkable.

### Fixed
- `problem_response` could not serialise a pydantic validation error, so any endpoint
  with a request-model validator returned 500 instead of 422 — latent API-wide.
- `secrets.project_id` was NOT NULL, which made a global LLM connection unable to hold
  a credential at all (migration 0006).
- Quota checks scanned the whole ledger while holding an advisory lock (migration
  0005 adds the scope indexes).

### Security
- CI grep-gate: no provider SDK may be imported outside `apps/mesh`.
- `presidio-anonymizer` was removed after the dependency audit showed its
  `cryptography <44.1` cap pulled in four known CVEs; it was never imported.

## [0.3.0] — Phase 2 · Flow & recipes (2026-07-23)

The transformation layer, and the canonical inspector + run-drawer patterns every
later module reuses (spec §7 Phase 2; decisions in ADR-0007). AC e2e: CSV → prepare →
join(Postgres) → group builds; a mid-flow edit rebuilds only the stale subset.

### Added
- **Recipes**: visual (prepare incl. select-columns, join, group, stack, split,
  sample) + code (SQL, Python) with single-producer + cycle validation, canonical
  Python-side config hashing (staleness), and before/after config audit
  (reconstructability). `GET /flow` view-model with a per-dataset status machine.
- **Engine** (`packages/engine`): Ibis→DuckDB recipe compilers; a safe AST expression
  language for formula/filter/split (no eval/exec — CI grep-gated; chained comparisons
  and division-by-zero handled); an allowlist SQL validator + secret-less execution
  (defense-in-depth against `duckdb_secrets()`/`read_parquet('s3://…')` exfiltration).
- **Preview** (§6.3(3)): `POST /recipes/{id}/preview` runs against sampled inputs and
  accepts a draft config to preview unsaved edits — never writes.
- **Jobs** (ADR-0007): a Postgres `FOR UPDATE SKIP LOCKED` queue + in-process
  JobExecutor with heartbeat/requeue (poison cap) and cancel; `POST /builds`
  (idempotent + coalescing) resolves and rebuilds only the stale upstream subset;
  atomic per-dataset advisory-locked version flip with profile refresh + CP-1 floor;
  S3 chunk logs with an offset tail; low-frequency job/step SSE.
- **Python sandbox** (spec §3.2/§10): `osaip` SDK IO broker; subprocess with a minimal
  env (no ambient credentials), per-limit rlimit guards, `unshare -n` network denial,
  and a wall-clock kill; a compensating control blocks Python recipes on special-
  category inputs until container isolation.
- **Web**: the Flow canvas (`packages/canvas`, @xyflow/react + dagre, living-Flow edge
  pulses), the canonical inspector (Configure · Preview · Runs · Lineage · Docs), the
  run drawer, jobs list/detail, and a dataset Lineage tab.
- **Seed v2.1**: a prebuilt `sales_enriched` recipe so the Flow renders alive.

### Decisions
ADR-0007 (job queue + JobExecutor, staleness hashing, log layout, sandbox incl.
no-network, worker→api import trigger, CP-1 ratchet floor + CP-2 intersection).

## [0.2.0] — Phase 1 · Connections & datasets (2026-07-23)

Data foundation (spec §7 Phase 1 + Compliance Pack CP-1/CP-2 v1). All three phase ACs
are named Playwright specs: CSV upload → typed schema + profile (11), Postgres table
registered → preview (12), bad creds fail cleanly without leaking (13).

### Added
- **Secrets**: MultiFernet vault (comma-separated key list, startup validation,
  rotation = prepend + lazy re-encrypt, per-ciphertext key_id) — ADR-0006.
- **Connections** (postgres · s3 · duckdb_file): admin-only CRUD + sanitized
  test-connection + preview-first `inspect`; CP-2 legal basis + purpose codes
  required; platform-DB SSRF denylist; archive blocked while referenced.
- **Engine** (`packages/engine`): the single S3 storage interface (boto3,
  SeaweedFS identities in dev), DuckDB adapter — exact-pinned duckdb, baked
  extensions with autoinstall off, thread offload + bounded semaphore + interrupt
  watchdog, injection-safe SQL assembly (`sql_literal`/`sql_ident` + tests),
  explicit-aggregate profiling, READ_ONLY postgres/duckdb attaches.
- **Datasets**: preview-first upload (raw → transient prefix, inferred schema +
  preview, confirm → typed parquet v1 + stored profile; 413 stream guard, xlsx
  zip-bomb cap) and register-from-connection (postgres table with reltuples
  estimates, s3 parquet, duckdb_file); sample endpoint with version-keyed ETags
  (304 = zero engine work) vs no-cache for external kinds; viewer-readable stored
  profiles; CP-1 tri-field labels (classification/BBN/vertrouwelijkheid) on
  datasets AND columns; `params` records inference decisions; SSE `datasets` topic.
- **Web**: datasets list/detail (deep-linkable tabs, sample grid, profile stats,
  inline column labels), upload + register panels, connections settings tab with
  URL-synced tabs; bundle 207/300 KB gz.
- **Seed v2**: per-resource idempotent; real `sales_orders` (60-row CSV → parquet +
  profile) and `demo_src.sales` (40 rows) for the AC-2 path.

### Fixed
- Latent Phase-0 bug: members PUT crashed on adding 2+ new members at once
  (string UUIDs vs insertmanyvalues sentinel matching).

## [0.1.0] — Phase 0 · Foundation & app shell (2026-07-22)

First working vertical slice of the platform (spec §7 Phase 0 + Compliance Pack P0).

### Added
- **Monorepo**: uv workspace (api, worker, 7 packages incl. the `osaip` SDK stub) +
  pnpm workspace (web, ui, canvas, api-client); Makefile (`dev|test|e2e|lint|seed|ci|gen-api`).
- **Dev stack**: docker compose with postgres 16 + pgvector, SeaweedFS, ephemeral
  Keycloak (pre-imported `osaip` realm, dual-hostname OIDC), api (auto-migrating),
  worker, web. Zero-click `make dev`.
- **Auth**: OIDC BFF (code+PKCE server-side, server-side sessions, hashed session
  tokens, CSRF Origin/Sec-Fetch-Site guard, RP-initiated logout) — ADR-0001.
- **Projects**: CRUD + membership RBAC (viewer/editor/admin + site admin) through a
  single permissions module; server-computed capability flags; idempotency keys;
  ETags; keyset pagination.
- **Audit**: hash-chained append-only audit log (CP-7) with canonical serialization
  stable across jsonb round-trips, advisory-lock serialized writes, DB triggers
  blocking UPDATE/DELETE/TRUNCATE, and a batched verification endpoint — ADR-0005.
- **Event bus**: single multiplexed SSE channel with a bigserial cursor, LISTEN
  wake-ups, one code path for live tail + Last-Event-ID replay, membership-filtered
  visibility, worker-side retention — ADR-0003. Notifications inbox + toasts ride it.
- **Search**: `object_refs` registry with generated tsvector; membership-filtered
  prefix FTS behind `GET /search`; powers the ⌘K omnibar (hybrid pgvector in Phase 3).
- **Design system** (`@osaip/ui`): token contract (graphite neutrals, violet accent,
  status palette, IBM Plex, motion + reduced-motion, density), 16 components,
  Storybook with theme/density toolbars, token-contract tests.
- **App shell**: §6.2 rail IA with phase-labeled stubs, top bar (project switcher,
  ⌘K, placeholder run-bell/approvals/copilot, user menu), projects screens
  (non-modal create panel, onboarding checklist, settings with members + audit
  tabs), consumer `/hub` stub, dark mode, full keyboard paths.
- **Generated API client**: `@hey-api/openapi-ts` + TanStack Query options from the
  typed OpenAPI (`make gen-api`), with a CI drift gate. Hand-written fetch is
  forbidden (single recorded SSE exemption).
- **Compliance (CP-7/12/13/14)**: SECURITY.md + `/.well-known/security.txt`;
  CycloneDX SBOMs, pip-audit/pnpm audit, license allowlist gate (ADR-0004);
  axe accessibility checks in e2e; vendored NL REST API Design Rules spectral
  ruleset with justified overrides; NLGov-aligned Keycloak realm preset asserted by
  tests; deployment checklist (NCSC TLS, HSTS, DNSSEC, NTP).
- **CI**: ruff, mypy --strict, pytest (testcontainers), eslint, tsc, vitest,
  Playwright acceptance suite (AC 1–7, axe, mobile, error/loading states, visual
  smoke), bundle-size budget, supply-chain job.

### Decisions
ADR-0001 BFF OIDC · ADR-0002 asyncpg (license) · ADR-0003 SSE design ·
ADR-0004 license exceptions (ISC, OFL-1.1, MPL-2.0 dev-only; elkjs→dagre swap, user-approved) ·
ADR-0005 Compliance Pack P0 adoption with recorded deferrals.
