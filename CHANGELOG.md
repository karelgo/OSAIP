# Changelog

All notable changes to OSAIP. Format loosely follows Keep a Changelog; the project is
pre-1.0, so minor versions may break.

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
