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

## Secrets & object storage (Phase 1, ADR-0006)

- [ ] **`OSAIP_SECRET_KEY` replaced** — never the dev default. One or more
      urlsafe-base64 32-byte Fernet keys, comma-separated (first key encrypts;
      rotation = prepend a new key). Store in a secret manager, not in compose files.
- [ ] **S3 credentials replaced** (`OSAIP_S3_ACCESS_KEY`/`OSAIP_S3_SECRET_KEY`) and
      scoped to the platform bucket only; `OSAIP_S3_USE_SSL=1` against a TLS
      endpoint. SeaweedFS identities (`-s3.config`) are dev-only.
- [ ] Bucket lifecycle/backup policy for `projects/` decided (datasets are versioned
      parquet; raw uploads are transient and pruned after 24h by the worker).

## Recipe execution & the Python sandbox (Phase 2, ADR-0007)

- [ ] **Run the worker on Linux** in production — the Python-recipe sandbox denies
      network via `unshare -n` and enforces `RLIMIT_AS` only on Linux; on macOS dev
      both are degraded (documented). A non-Linux worker is not a compliant sandbox.
- [ ] The sandbox is subprocess isolation, **not** container isolation (a later
      hardening). Until then, Python recipes on `bsn`/`bijzonder`/`bbn3`-labelled
      inputs are blocked by a compensating control (BIO2 8.12 — see COMPLIANCE_NL.md
      §3.3 note). Do not weaken that gate before container isolation lands.
- [ ] Tune `OSAIP_SANDBOX_CPU_SECONDS` / `_MEM_BYTES` / `_WALL_SECONDS` and
      `OSAIP_DUCKDB_BUILD_MEMORY_LIMIT` / `_PREVIEW_MEMORY_LIMIT` /
      `OSAIP_ENGINE_CONCURRENCY` to the host; set a spill `temp_directory` for large
      builds. Run one worker per host (job claiming is `FOR UPDATE SKIP LOCKED`, safe
      to scale horizontally).
- [ ] Job logs (`projects/<key>/artifacts/jobs/…`) are a personal-data-bearing
      stream (user `print`s, error values): they inherit the max input classification
      and get an interim 30-day TTL prune. Fold them into the CP-3 retention engine
      when it lands (Phase 8).

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

## LLM Mesh (Phase 3)

- [ ] `OSAIP_MESH_SERVICE_TOKEN` set from a secret store, and NOT the dev default. The
      mesh has no other authentication and is never published to the browser.
- [ ] The mesh service has **no published port** in your compose/Helm values — every
      model call goes through it, so nothing may reach a provider around it (§5b).
- [ ] Each LLM connection's `data_residency` reflects reality. It is
      **operator-asserted metadata**: OSAIP enforces your declaration and audits it, but
      cannot verify where a remote endpoint runs (ADR-0008 §7). Getting this wrong
      silently defeats the CP-11 gate — record the basis for each declaration in your
      DPIA.
- [ ] `audit_mode` per connection is a deliberate choice. `redacted` (default) stores no
      raw prompt text; `full` retains it and is site-admin-only; `off` stores no message
      text at all. `full` and `off` both belong in the DPIA.
- [ ] Every connection has a quota (§10: budgets are mandatory from Phase 3). Decide
      `warn` vs `block` per scope; `block` returns 429 `quota-exceeded`.
- [ ] `llm_calls` / `llm_call_messages` / `spans` retention ≥ 6 months (AI Act Art
      26(6)); the worker prune never deletes inside the window.
- [ ] Review `model_prices.json` (`_verified_on`) against your contracts. An unpriced
      model costs 0 and is flagged `pricing_unknown` — the platform never guesses.

### Optional: Dutch NER (name/place detection)

The deterministic PII layer — BSN (11-proef), IBAN (mod-97), email, phone — is **always
on** and needs no model, no network and no extra step.

Model-backed detection of names, places and dates is opt-in because the Dutch spaCy
model is **CC BY-SA 4.0** and OSAIP does not redistribute it (ADR-0009). To enable it:

- [ ] Install the pinned wheel into the image or runtime environment:
      `uv pip install "https://github.com/explosion/spacy-models/releases/download/nl_core_news_sm-3.8.0/nl_core_news_sm-3.8.0-py3-none-any.whl"`
      — stage the file yourself for an air-gapped install; OSAIP never downloads a model
      at runtime.
- [ ] Set `presidio: true` in the `pre` stage of a guardrail policy, and attach that
      policy to the connections that need it.
- [ ] Confirm it is actually loaded before relying on it: without the model the mesh
      raises rather than silently falling back to regex-only.

## Not yet in scope (tracked deferrals, ADR-0005)

- SIEM/syslog(CEF) export of audit/ledger streams — lands Phase 3.
- TLS preset as code (Helm values) — lands with the production deployment config.
- Toegankelijkheidsverklaring generator — lands Phase 4 with the public Hub.
