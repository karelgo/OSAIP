# Security policy

OSAIP is a self-hostable AI/data platform. We take vulnerability reports seriously and
follow coordinated vulnerability disclosure (CVD).

## Reporting a vulnerability

- Email: **security@osaip.dev** (placeholder until the project has a public home —
  operators deploying OSAIP should replace this with their own security contact and
  regenerate `/.well-known/security.txt`).
- Please include: affected component/version, reproduction steps, impact assessment,
  and any suggested fix. Encrypted reports are welcome (key published alongside
  security.txt once available).

## What to expect (CVD process)

1. **Acknowledgement within 3 business days.**
2. Triage and severity assessment (CVSS) within 10 business days.
3. We develop and test a fix; we may ask you to validate it.
4. Coordinated publication: we credit reporters (unless you prefer otherwise) and
   publish an advisory + patched release. Target: within 90 days of report, faster
   for critical issues.

We will not pursue legal action for good-faith research that respects scope: no data
exfiltration beyond proof-of-concept, no service disruption, no access to other users'
data.

## Scope notes for deployers

- The dev compose stack (`make dev`) is explicitly **not** production-hardened: it uses
  a fixed Keycloak dev realm secret (allowlisted in secret scanning; see ADR-0005) and
  plaintext HTTP. See `docs/deployment-checklist.md` before any production use.
- Supported versions: pre-1.0, only the latest minor release receives fixes.

## Machine-readable contact

`/.well-known/security.txt` (RFC 9116) is served by both the API and the web app.
