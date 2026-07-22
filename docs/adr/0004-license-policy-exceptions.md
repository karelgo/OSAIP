# ADR-0004: License-policy exceptions (ISC, OFL-1.1, MPL-2.0 dev-only) and the elkjs flag

Status: Accepted · 2026-07-22 · Phase 0

## Context
Spec §3.1 (LOCKED) allowlists Apache-2.0 / MIT / BSD / PSF / PostgreSQL for in-process
dependencies. Three needed licenses fall outside the letter of that list, and one
Phase 1 locked pick has a real conflict. The CI license gate (CP-12) enforces the
allowlist, so every exception must be recorded here and mirrored in the gate config.

## Decision
Recorded exceptions, scoped as narrowly as stated:
1. **ISC — lucide (icons).** ISC is OSI-approved and functionally identical to
   MIT/BSD-2. Accepted for in-process use; ISC added to the gate allowlist.
2. **OFL-1.1 — IBM Plex Sans/Mono font assets.** Spec §6.4 itself picks these fonts.
   OFL is the standard font-embedding license; its Reserved-Font-Name clause only
   bites on modification/renaming. Accepted for **unmodified font files only** —
   never for code.
3. **MPL-2.0 — `@axe-core/*` (incl. `@axe-core/playwright`).** Dev/CI-only a11y
   testing (CP-13); never shipped in the product bundle. Accepted for build/test
   tooling only.

**Resolved (user decision, 2026-07-22): dagre replaces elkjs.** Spec §3.2 originally
picked `elkjs`, which is licensed EPL-2.0 OR GPL-3.0-or-later — neither is on the
allowlist, and it would run in-process in the browser. With explicit user approval
(§9.6) the graph-layout engine is now **`@dagrejs/dagre` (MIT)**; PROJECT_SPEC.md
§3.2/§6.5 have been updated. No EPL/GPL exception exists — the gate still blocks both.

## Consequences
The CI gate allowlist = §3.1 list + ISC (code) + OFL-1.1 (font assets) + MPL-2.0
(devDependencies only). Any new license → new ADR entry before the dependency lands.
