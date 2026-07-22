# Production deployment checklist (CP-14, CP-7 · ADR-0005)

The dev compose stack is NOT production-ready: it uses fixed dev credentials, plain
HTTP, and an ephemeral Keycloak. Before any production or citizen-adjacent use, walk
this list. Items marked [org] are organisational, not platform switches.

## Transport & endpoint security (NCSC / Forum Standaardisatie)

- [ ] TLS terminates at a reverse proxy in front of api/web with an
      **NCSC-conformant configuration** (current NCSC "ICT-beveiligingsrichtlijnen
      voor TLS": TLS 1.3 preferred, TLS 1.2 minimum with approved suites only).
      Example nginx snippet:

      ```nginx
      ssl_protocols TLSv1.3 TLSv1.2;
      ssl_ciphers ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256;
      ssl_prefer_server_ciphers on;
      add_header Strict-Transport-Security "max-age=63072000; includeSubDomains" always;
      ```

- [ ] **HSTS** enabled (see above); preload after a bake-in period.
- [ ] **DNSSEC** on all public zones (pas-toe-of-leg-uit).
- [ ] Cookies: `OSAIP_DEV=0` so session cookies get the `Secure` flag; confirm
      `SameSite=Lax` + `HttpOnly` in responses.

## Identity

- [ ] Replace the dev realm entirely: no `osaip-dev-secret`, no fixed user ids, no
      password `dev`. Client secret from a secret store.
- [ ] Keycloak (or your OIDC provider) behind TLS; `OSAIP_OIDC_ISSUER` = public
      https URL; token lifetimes reviewed (realm preset keeps access tokens ≤ 5 min).
- [ ] DigiD/eHerkenning brokering (if citizen/company login is ever needed) via the
      NLGov OIDC profiles — new ADR required first.

## Time & evidence integrity (CP-7)

- [ ] **NTP/chrony on every host** — the audit chain's `ts` values are evidence;
      undisciplined clocks undermine their value (BIO2 8.17).
- [ ] Audit retention configured ≥ 6 months (AI Act Art 26 default; align with the
      applicable Archiefwet selectielijst before extending/shortening).
- [ ] Run `POST /api/v1/audit/verify` on a schedule; alert on failure.

## Data & backups

- [ ] Postgres: managed instance or hardened self-hosted; backups + restore drill
      documented (BIO2 8.13-8.14).
- [ ] Object storage: production S3-compatible endpoint with TLS + bucket policies
      (SeaweedFS is the DEV default only).
- [ ] `OSAIP_SESSION_SECRET` from a secret store; rotate on suspicion.

## Supply chain (CP-12)

- [ ] Build images from pinned digests; enable the cosign signing step when images
      are first published to a registry.
- [ ] Keep SBOM artifacts from CI with each release.
- [ ] [org] Point `/.well-known/security.txt` Contact at the real security office
      and publish the CVD policy.

## Not yet in scope (tracked deferrals, ADR-0005)

- SIEM/syslog(CEF) export of audit/ledger streams — lands Phase 3.
- TLS preset as code (Helm values) — lands with the production deployment config.
- Toegankelijkheidsverklaring generator — lands Phase 4 with the public Hub.
