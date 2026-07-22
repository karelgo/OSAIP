# ADR-0005: Compliance Pack P0 adoption (CP-7, CP-12, CP-13, CP-14)

Status: Accepted · 2026-07-22 · Phase 0 · Amends spec §7 Phase 0 (user-approved)

## Context
COMPLIANCE_UWV.md §5 defines a Compliance Pack; items CP-7, CP-12, CP-13, CP-14 are
tagged [P0]. The user approved folding them into Phase 0. Some sub-elements genuinely
belong later; this ADR records what ships now and every explicit deferral, so no
sub-element is silently dropped.

## CP-7 — Evidence-grade logging
**Now:** hash-chained append-only `audit_log`. Canonicalization is RFC-8785-style JSON
(sorted keys, compact separators, no NaN/Inf) over values **as a DB read-back yields
them**: `ts` as fixed-width UTC ISO-8601 with microseconds, `ip` as text, details as
JSON text. `row_hash = sha256(prev_hash ‖ canonical(row))`; genesis = 64 zero chars.
Writes take `pg_advisory_xact_lock(hashtext('osaip_audit'))`, read the head by
`seq DESC LIMIT 1`, and insert — as the LAST operation inside the mutation's own
transaction (atomic with the mutation, minimal lock hold). `seq` (identity column) is
the chain order; the lock makes seq order = commit order. Triggers block
UPDATE/DELETE/TRUNCATE. Verification is a batched Python service reading fresh rows
(`POST /audit/verify`, site admin). Retention default **≥ 6 months**,
Archiefwet/selectielijst-configurable.
**Deferred:** retention *enforcement* engine → CP-3 (P8); SIEM/syslog(CEF) export → P3
(lands with the OTel trace stack); NTP/clock-sync is a deployment-checklist item now.

## CP-12 — Supply-chain integrity
**Now:** CycloneDX SBOM per release (cyclonedx-bom for Python, cdxgen for pnpm),
pip-audit + pnpm audit gates, license-allowlist gate (see ADR-0004), `SECURITY.md`
(coordinated vulnerability disclosure policy) + `/.well-known/security.txt` served by
api and web with a CI check.
**Deferred:** cosign image signing → activates in the first phase that *publishes*
images to a registry (Phase 0 builds but does not publish); the CI hook is stubbed.

## CP-13 — Accessibility conformance
**Now:** automated axe (WCAG 2.1 AA subset) checks in Playwright CI over login, home,
project, settings, `/hub` stub, and representative stub routes; gate = zero
serious/critical, moderates reported. Automated scanning covers only part of
EN 301 549 — manual audit remains for the formal statement.
**Deferred:** toegankelijkheidsverklaring generator → P4, when Hub becomes a real,
publicly deployable surface (aligns with CP-6 transparency surfaces).

## CP-14 — NL standards presets
**Now:** Keycloak realm preset aligned to NLGov OIDC profile intent — code+PKCE only,
confidential client, no implicit/hybrid flows, RS256/PS256 signing, short token
lifetimes, exact redirect URIs; the realm export is asserted by a pytest so drift
fails CI. Conformance matrix: PKCE enforced ✔ · exact redirect URIs ✔ · signed tokens ✔
· claims per NLGov naming ◐ (defaults; revisit with DigiD/eHerkenning brokering) ·
mTLS/private_key_jwt client auth ✗ (deferred to production hardening).
Spectral linting of the exported OpenAPI against a **vendored, pinned** NL REST-API
Design Rules ruleset; per-rule overrides live in `.spectral.yaml`, each with a one-line
justification (e.g. `/auth/login` and `/notifications/{id}/read` are deliberate
action-verb paths). `API-Version` response header via middleware.
`docs/deployment-checklist.md`: NCSC-conformant TLS (with example reverse-proxy
snippet), HSTS, DNSSEC, NTP/clock discipline (audit timestamp integrity).
**Deferred:** production TLS preset artifact → ships with the prod deployment config;
full official adr-validator ruleset adoption tracked as follow-up.

## Also recorded
Hybrid (FTS + pgvector) `/search` per §6.6 ships FTS-only in Phase 0; the pgvector
column is reserved and hybrid lands in **Phase 3** when the mesh can produce embeddings.

## Consequences
Phase 0 carries ~1–2 days of extra scope; in exchange the audit stream is
evidence-grade from the first commit, and every deferral above is a tracked decision
an auditor can follow rather than a silent gap.
