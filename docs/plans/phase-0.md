# Phase 0 — Foundation & app shell

Status: **approved** (user, 2026-07-22). Decisions: adopt Compliance Pack P0 items
CP-7/12/13/14 (COMPLIANCE_UWV.md §5); product name **OSAIP** (`osaip` packages, `@osaip`
npm scope, Keycloak realm `osaip`); CI on GitHub Actions. Draft was adversarially
reviewed by 4 verifier agents; their blockers/majors are folded in below.

## Scope (spec §7 Phase 0 + CP items)
1. Monorepo per §3.3 — uv workspace (Py 3.12) + pnpm workspace (Node 22).
2. `infra/compose`: postgres16+pgvector, SeaweedFS, Keycloak (pinned, ephemeral — realm JSON is code, re-imports every boot), api, worker (heartbeat + event-prune only; queue is P2), web.
3. OIDC BFF login (Authlib, code+PKCE server-side): server-side `sessions` table; cookie = signed random session id (HttpOnly, SameSite=Lax, Secure in prod); tokens never reach the browser; access/refresh discarded post-callback, id_token kept for RP-initiated logout. CSRF: Origin/Sec-Fetch-Site middleware on non-GET; `?next=` same-origin relative only. Auto-provision users. (ADR-0001)
4. Projects CRUD + RBAC: `is_site_admin`; roles viewer < editor < admin; one `permissions` module; server-computed capability flags (§6.6).
5. Hash-chained append-only audit log (CP-7; ADR-0005).
6. Design system v1 (`packages/ui`): CSS-var tokens — graphite neutrals, one accent, status palette, IBM Plex Sans/Mono (OFL, self-hosted), 4px grid, light+dark, density, motion 120–200ms + `prefers-reduced-motion`; ~14 components; Storybook.
7. App shell: rail IA §6.2; top bar (project switcher recents+search, ⌘K, run-bell/approvals/copilot placeholders, user menu); phase-labeled stub routes; `/hub` stub (mobile-usable); onboarding checklist on project home (§6.3(9)).
8. ⌘K omnibar: `GET /search` (FTS over `object_refs`; hybrid+pgvector lands P3 — deferral in ADR-0005) + action registry skeleton.
9. SSE event bus + notifications inbox (ADR-0003).
10. CI + `make ci`: ruff, mypy --strict (packages/), pytest (testcontainers), eslint, tsc, vitest, Playwright + axe (CP-13) + visual smoke, bundle gate < 300 KB gz; CycloneDX SBOM, pip-audit + pnpm audit, license-allowlist gate (CP-12).
11. CP-12 rest: SECURITY.md (CVD) + `/.well-known/security.txt` on api & web; cosign deferred to first image publish (ADR-0005).
12. CP-14: NLGov-profile Keycloak realm (conformance matrix in ADR-0005, settings pinned by test); vendored+pinned NL REST-API Design Rules Spectral ruleset with justified overrides; `API-Version` header middleware; `docs/deployment-checklist.md` (NCSC TLS + example proxy snippet, HSTS, DNSSEC, NTP for audit timestamp integrity).
13. CP-13 rest: toegankelijkheidsverklaring generator deferred to P4 (ADR-0005).

Out of scope: datasets/connections (P1; seed inserts a `dataset` object_ref so the ⌘K AC is real), jobs/queue (P2), SIEM/CEF export (P3 half of CP-7).

## Endpoints (`/api/v1`; problem+json `{type,title,status,detail,hint,docs_url}`; cursor pagination; idempotency keys on POSTs; ETags on `GET /projects[/{key}]`)
- `GET /healthz` · `GET /readyz`
- `GET /auth/login?next=` · `GET /auth/callback` · `POST /auth/logout` (kills session row → Keycloak end-session with `id_token_hint`)
- `GET /me` · `PATCH /me/prefs`
- `GET|POST /projects` · `GET|PATCH|DELETE /projects/{key}` (DELETE=archive; archived rejects member edits)
- `GET|PUT /projects/{key}/members` (full replace; ≥1 admin else 409) · `DELETE /projects/{key}/members/{user_id}`
- `GET /projects/{key}/audit` · `GET /audit`, `POST /audit/verify` (site admin, batched)
- `GET /search?q=&project=&kinds=` · `GET /events?topics=` (SSE)
- `GET /notifications` · `POST /notifications/{id}/read` · `POST /notifications/read-all`
- `POST /dev/emit-test-event` (only when `OSAIP_DEV=1`)

## Schema (Alembic 0001; UUIDv7 PKs via shared `packages/shared` helper — ids never ordering keys)
users(oidc_sub uq, email, display_name, is_site_admin, last_login_at) ·
sessions(user_id, oidc_sub, oidc_sid idx, id_token, expires_at) ·
groups + group_members (minimal) ·
projects(key uq, name, description, status, storage_prefix, created_by) ·
project_members(project_id, user_id, role) ·
audit_log(id, **seq identity**, ts, actor_id, project_id?, action, object_kind, object_id, details_json, ip, prev_hash, row_hash) ·
object_refs(kind, project_id, name, description, url_path, tsv generated + GIN) ·
events(id, **seq bigserial**, ts, topic, project_id?, user_id?, type, payload_json) ·
notifications(user_id, kind, severity, title, body, ref_kind, ref_id, read_at) ·
user_prefs(theme, density, pinned_json) ·
idempotency_keys(key, user_id, method_path, request_hash, response_status, response_body; 24h prune)

**Audit chain (ADR-0005):** RFC-8785-style canonical JSON over values as a DB read-back
yields them (ts = UTC ISO µs, ip as text); `row_hash = sha256(prev_hash ‖ canonical)`;
genesis 64 zeros; write = `pg_advisory_xact_lock(hashtext('osaip_audit'))` → head by
`seq DESC LIMIT 1` → insert, LAST op in the mutation's txn; chain order = seq; triggers
block UPDATE/DELETE/TRUNCATE; verification is a batched Python service over fresh reads.
Retention default ≥ 6 months (Archiefwet-configurable; enforcement engine = CP-3, P8).

**SSE (ADR-0003):** `seq` is the SSE id/cursor; NOTIFY is an empty wake-up; every wake-up
and reconnect runs `WHERE seq > cursor ORDER BY seq` (one path for live + replay; kills
the commit-order race and the 8KB NOTIFY limit); short advisory lock around event INSERT;
one dedicated LISTEN connection per process → per-client bounded queues (overflow ⇒
disconnect, client resumes via Last-Event-ID); single `event_visible(user, event)`
predicate for live AND replay; worker prunes at 7 days, stale cursor ⇒ `reset` control
event (client invalidates all queries); 15s heartbeats.

## Components
`packages/ui` (~14): Button, Input, Select, Checkbox, Badge, Tabs, Dialog, DropdownMenu,
Tooltip, Toast, Table, Skeleton, EmptyState, Command (cmdk) + ThemeProvider/tokens.
`apps/web`: routes `/login`, `/` (projects home), `/p/$key` (+onboarding checklist),
rail stubs, `/hub`; feature-sliced; Zustand shell state; forms = react-hook-form + zod;
optimistic mutations with idempotency keys; **project creation is a side-panel/route,
not a modal** (§6.3(2)). `packages/api-client`: @hey-api/openapi-ts (pinned) + TanStack
Query plugin from exported openapi.json; `make gen-api`; CI drift gate; hand-written
fetch forbidden (single recorded exemption: the EventSource SSE client).
Keycloak: realm `osaip`, client `osaip-api`; `KC_HOSTNAME=localhost:8080` (issuer =
localhost); Authlib explicit endpoints — authorize browser-facing, token/JWKS
container-internal, `iss` asserted; `KC_HEALTH_ENABLED=true` + /dev/tcp healthcheck on
9000; no volume ⇒ deterministic re-import; fixed dev secret in realm JSON, allowlisted.

## Test list
**pytest:** permissions matrix; projects CRUD (viewer 403, idempotency replay, cursor
pagination, ETag/304, last-admin 409, problem+json fields); audit (row per mutation,
verify from fresh read, tamper detection, append-only + TRUNCATE triggers); auth
(provisioning, session row, logout, CSRF cross-origin rejected, `next` open-redirect
rejected); realm-settings assertions; search membership filtering; SSE (stream via
httpx-sse, Last-Event-ID replay incl. out-of-order commits, visibility); notifications;
security.txt. **vitest:** token contract (light/dark/reduced-motion); action registry;
SSE invalidation map; component smoke. **Playwright** (built output on one origin, NOT
dev proxy; chromium, 1 worker, fresh context per role): 1 Keycloak login→home (AC-1) ·
2 create project + audit entry (AC-2/4) · 3 viewer blocked UI+API (AC-3) · 4 keyboard-
only walk in dark mode (AC-5) · 5 ⌘K → seeded dataset (AC-6) · 6 test event → toast +
inbox via SSE (AC-7) · 7 axe on login/home/project/settings/hub/stubs, zero
serious+critical · 8 /hub mobile viewport · 9 error (500 ⇒ hint+retry) + skeleton states
· 10 visual smoke (Storybook + shell, linux baselines).

## New dependencies (licenses verified; §3.1)
Py: fastapi/sqlalchemy/alembic MIT · uvicorn/authlib/itsdangerous/sse-starlette/httpx
BSD-3 · **asyncpg Apache-2.0 (psycopg is LGPL — ADR-0002)** · uuid6/httpx-sse/
pydantic-settings/pytest/ruff/mypy MIT · orjson Apache/MIT · testcontainers Apache-2.0.
Web: react/tanstack/zustand/cmdk/radix/shadcn/tailwind/vite/vitest/storybook/eslint/
react-hook-form/zod/clsx/tailwind-merge/@hey-api/openapi-ts MIT · cva/typescript/
playwright Apache-2.0. CI-only: cyclonedx-bom/cdxgen/spectral/pip-audit Apache-2.0 ·
license-checker BSD-3. **ADR-0004 exceptions:** ISC (lucide) · OFL-1.1 (IBM Plex assets)
· MPL-2.0 (`@axe-core/*`, dev/CI-only) · forward flag: elkjs is EPL-2.0/GPL — resolve
before P1. Containers (out-of-process): Keycloak/SeaweedFS Apache-2.0 · Postgres/pgvector
PostgreSQL.

## Risks
Keycloak CI flake → pinned image, ephemeral realm, tcp healthcheck, health-gated deps.
Audit-lock contention → lock only wraps head-read+insert at txn end; low volume.
SSE dev-proxy buffering → e2e uses built output; dev proxy: buffering off + heartbeats.
hey-api pre-1.0 churn → pinned, generated output committed, drift gate.
Visual-diff flake → linux-only baselines, animations disabled.
Spectral ADR rules failing by design (e.g. /auth/login verb path) → vendored ruleset,
justified per-rule overrides decided upfront (ADR-0005).

## Slices (1 commit each, `make test` green)
0 repo+docs · 1 scaffold+compose+CI · 2 API base+migration+audit · 3 auth · 4 projects/
RBAC · 5 packages/ui · 6 web shell+api-client · 7 projects UI · 8 search+omnibar ·
9 SSE+notifications · 10 seed+e2e+full CI+docs.

## Definition of done
`make dev` clean from scratch (zero clicks) → `make seed` → `make ci` green (all 10
Playwright specs; §7 AC 1–7 each named); SBOM artifacts; license gate with recorded
exceptions; OpenAPI ADR lint; bundle budget. §6.7 checklist on every new screen (login,
home, project home, settings, inbox, /hub mobile, stubs). Audit tamper test proves the
chain from a fresh read. Then demo seed, docs + CHANGELOG, summary, stop (§9.4).
