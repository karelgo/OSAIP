# Phase 3a — LLM Mesh foundation

Status: **approved** (user, 2026-07-29). Spec §7's Phase 3 was split after a 4-lens
adversarial review returned 98 findings (24 blockers): **3a** = the mesh foundation
(this plan); **3b** = LLM recipes in the Flow, Prompt Studio, and the spec §7 AC e2e.
Decisions in ADR-0008.

**Decisions:** built-in **echo provider** (hermetic, free CI) + **Ollama** compose
profile + real providers via key; **Presidio lazy-loaded** with the Dutch
**`nl_core_news_sm`** model behind a deterministic regex layer.

**3a acceptance:** a mesh call through two different connections (echo + an
OpenAI-compatible stub exercising the real LiteLLM path) shares one code path · the
ledger shows tokens+cost+provider/model/version per call · a low quota blocks with a
clear error · a BSN-bearing prompt is stored redacted and the raw never persists · a
`bsn`-labelled payload to an `external` connection is hard-blocked with an audit event.

## Scope
1. **`apps/mesh`** (§3.3): own FastAPI service sharing the api image; compose service +
   healthcheck + e2e/CI boot list; workspace member in the mypy/lint gates. Internal
   `POST /v1/complete`, service-token auth, never browser-reachable. Pipeline
   (ADR-0008 §1): authz → CP-11 gate → guardrails `pre` (redact) → quota reserve →
   cache (on redacted) → provider → guardrails `post` → settle (ledger+audit+span).
   `/v1/stream` **deferred to 3b/P4** with its post-guardrail design (nothing consumes
   streams in 3a) — recorded.
2. **Providers**: `Provider` protocol; `echo` (deterministic, token-counted, labelled,
   refuses non-`local` residency) and `litellm` (pinned exact, wrapped per §10) for
   openai-compatible/anthropic/ollama; per-call config (no global leakage), unknown
   params rejected. **SSRF-guard** every user-supplied `base_url` (§8) on save and
   before each call (deny link-local/metadata/private unless allowlisted).
3. **Migration 0004** (§4 verbatim + attribution): `llm_connections(scope
   global|project, project_id?, name, provider, base_config, allowed_models[],
   secret_id?, guardrail_policy_id?, cache_ttl_s, audit_mode, **data_residency**,
   **legal_basis, purpose_codes[]**, status)` · `llm_calls(… trace_id, agent_id?,
   session_id?, provider, model, model_version?, tokens_in/out, cost_micros, currency,
   latency_ms, cache_hit, guardrail_events_json, request_hash, **job_id?, job_step_id?,
   row_key?**)` · `llm_call_messages(call_id, seq, role, content_redacted,
   content_raw?)` · `traces` + `spans` (§4) · `llm_cache` · `quotas(scope incl.
   **agent**, period, limit_cost_micros, limit_calls, action)` · `guardrail_policies` +
   `guardrail_events` · `prompts`. Retention class ≥ 6 months on calls/messages/spans
   (CP-7, Art 26(6)); worker prune honors it.
4. **Cost** (ADR-0008 §2): pinned `model_prices.json` (verified-on date) → integer
   `cost_micros` + `currency` (EUR), half-up on the total; unknown model → 0 +
   `pricing_unknown`; tiktoken only as a flagged `tokens_estimated` fallback.
5. **Quotas — reserve/settle** (ADR-0008 §3): advisory-locked windowed sum *including
   reservations* → reserve (max_tokens worst case) → settle to actual; warn → header +
   notification; block → 429 `quota-exceeded` (≠ `provider-rate-limited`); worker
   sweeps abandoned reservations. Seed ships default budgets (§10).
6. **Guardrails** (`packages/guardrails`, stage protocol): `pre` = regex (**BSN
   11-proef**, IBAN mod-97, email, phone) → Presidio (lazy, `nl_core_news_sm`, via
   `run_engine` thread offload) → max-tokens; `post` = judge (purpose=guardrail +
   **depth counter**, itself ledgered) + JSON-schema. **Baseline redaction policy is
   non-removable** (BIO2 8.12).
7. **§5d posture** (release-blocking, §8): system prompts assembled **server-side from
   the registry**; all untrusted content via one documented `untrusted_block()` helper
   (tagged, escape-neutralised, user-role); injection matrix asserts the embedded
   instruction is not followed. Red-team eval set → P7; fixtures → 3b seed.
8. **CP-11 at the choke point** (ADR-0008 §7): mesh `pre` stage on the caller-declared
   max CP-1 classification; `bsn`/`bijzonder`/`bbn3` → `local` only, else 403 +
   `guardrail_events` + audit; **missing declaration fails closed** (treated
   `bijzonder`). Residency is operator-asserted metadata, documented as such.
9. **API + web**: connections CRUD (global site-admin + project scope, admin-only,
   secrets write-only, residency + CP-2 fields, test-connection), quotas CRUD, usage
   rollup (ETag), guardrail policies, prompts registry (Studio is 3b); object_refs +
   ⌘K. Web: **LLM connections** section in settings + **Usage** panel — full §6.7
   (skeleton, empty, error+retry, keyboard, dark, `?tab=` deep-link).
10. **Gates**: **grep-gate — no provider SDK import outside `apps/mesh`** (§5b) in
    Makefile + CI; license allowlist for litellm/presidio/spacy transitives; hermetic
    CI — spaCy model baked at image build from a pinned wheel, prices in-repo, echo
    needs no network.

Out of scope (recorded, with target): LLM recipes + Prompt Studio + §7 AC e2e → **3b** ·
`/v1/stream` + stream post-guardrails → 3b/P4 · KB/RAG (P4) · semantic (P5) ·
agents/tools + Trace Explorer UI (P6; spans accumulate now) · hybrid `/search`
embeddings (ADR-0005 deferral → 3b) · SIEM/CEF export (CP-7 P3 half → 3b) · Art 50
content marking (CP-6 → P4) · BSN pseudonymisation service (§3.5 Wabb → P5) ·
DPIA/FRIA objects (CP-4 → P7) · Redis cache · NeMo · vLLM.

## Endpoints
**mesh (internal):** `POST /v1/complete` · `GET /healthz`.
**api:** `GET|POST /llm-connections` (global, site-admin) · `GET|POST
/projects/{key}/llm-connections` · `GET|PATCH|DELETE .../llm-connections/{id}` ·
`POST .../llm-connections/{id}/test` · `GET|POST /projects/{key}/quotas` ·
`PATCH|DELETE .../quotas/{id}` · `GET /projects/{key}/usage?from=&to=&group_by=` ·
`GET|POST /projects/{key}/prompts` · `GET|PATCH .../prompts/{name}` ·
`GET|POST /guardrail-policies`.

## Key reuse
`Vault`/secrets · `sources.engine_problem` sanitization · `run_engine` offload
(Presidio) · `publish_event`/`write_audit` (ledger writes in their OWN short txn,
outside the audit advisory lock) · `etag_json_response` · `check_idempotency` · P1/P2
settings-tab + side-panel web patterns · `object_refs` upsert · e2e helpers.

## New dependencies (§3.1)
`litellm` (MIT, pinned exact) · `presidio-analyzer==2.2.362` + `presidio-anonymizer`
(MIT) · `spacy` (MIT) + `nl_core_news_sm` (**CC BY-SA 4.0 — NOT MIT as recorded here;
the §3.1 gate caught it. OSAIP does not redistribute the model; operators install the
pinned wheel themselves — ADR-0009**) ·
`tiktoken` (MIT, estimate-only). Verified: presidio 2.2.362 + spacy 3.8.14 + numpy
2.5.1 co-resolve.

## Test list
**mesh/unit**: pipeline order (blocked `pre` never reaches the provider; redaction
precedes cache+provider); cost math (micros, half-up, currency, unknown→flag); cache
(key normalization, project scoping, TTL, hit still ledgers + is redacted, judge/eval
never cached); quota reserve/settle under **concurrent calls** (no overshoot),
warn/block, quota-429 ≠ provider-429; guardrails (**BSN 11-proef true+false
positives**, IBAN mod-97, email; Presidio NL redaction; judge depth guard; schema);
**§5d injection matrix**; **CP-11** (bsn→external blocked + audit; missing declaration
fails closed); SSRF denial (metadata IP, private range); provider-error sanitization in
response **and ledger and logs**.
**api**: connections CRUD/RBAC/scope, secrets write-only; quotas CRUD + 429 shape;
usage values + ETag; prompts versioning; audit rows.
**e2e**: `16-llm-connection` (echo connection → test → usage shows tokens/cost) ·
`17-quota-block` (tiny quota → clear blocked error) · axe on the new surfaces.

## Risks
LiteLLM churn → pinned + wrapped. Presidio latency → lazy + offload + regex pre-filter.
Ledger volume vs the audit chain's global lock → ledger rows outside the chain. Cache
correctness → redacted key + no-cache for judge/eval. Residency self-asserted →
documented, not claimed as a guarantee. Air-gap → nothing fetched at runtime.

## Slices
0 docs + ADR-0008 · 1 migration 0004 + mesh skeleton + echo + SSRF + cost + wiring/
grep-gate · 2 ledger + traces/spans + audit storage + cache · 3 quotas reserve/settle +
usage · 4 guardrails + §5d + CP-11 · 5 LiteLLM provider + OpenAI-compatible stub ·
6 API (connections/quotas/usage/prompts/policies) · 7 web (connections + usage) ·
8 e2e 16-17 + seed v3 + CI + docs + CHANGELOG + summary.

## DoD
`make dev` clean (mesh healthy); `make seed` gives an echo connection + default quota;
`make ci` green incl. e2e 16-17, **hermetic**; §6.7 on both new screens; the five 3a
acceptance clauses asserted by named tests; grep-gate proves no provider SDK outside
`apps/mesh`; summary + stop (§9.4).

---

# Phase 3a summary (completed 2026-08-02)

## What shipped
`apps/mesh` — the gateway every model call passes through (§5b), reachable only by
service token and never published to the browser. The pipeline owns the ORDER:
CP-11 residency gate → guardrails `pre` (redact) → quota reserve → cache (on the
REDACTED payload) → provider → guardrails `post` → settle (ledger + audit + span).

- **Ledger** (§4): every call recorded with full attribution — job/step/row, trace and
  span, provider/model/model_version, tokens, integer cost micros + currency, latency,
  cache_hit, status. Ledger rows are plain inserts outside the audit chain's advisory
  lock; only policy-relevant events (a residency block) go into the hash-chained audit.
- **Audit storage**: `redacted` (default) keeps no raw copy; `full` keeps both and only
  where redaction changed something; `off` stores no text but still ledgers the call.
- **Budgets** by reserve/settle, not check-then-call. A committed hold is visible to
  concurrent callers, so N parallel calls cannot collectively overshoot; an abandoned
  hold is ignored on read after 15 minutes so a crashed process costs minutes of
  headroom, not a month. block → 429 `quota-exceeded`, deliberately distinct from a
  provider rate-limit.
- **Guardrails** (`packages/guardrails`, dependency-free): BSN 11-proef, IBAN mod-97,
  email, phone — checksum-verified, and matched in the groupings Dutch case files
  actually use. Events record counts, never values. The baseline is not configurable
  away (BIO2 8.12). §5d `untrusted_block()` is the only sanctioned way to interpolate
  untrusted content. Presidio NL is opt-in and operator-installed (ADR-0009).
- **Providers**: `echo` (deterministic, free, refuses non-local residency) and the
  LiteLLM adapter covering openai-compatible / anthropic / ollama, wrapped behind our
  own protocol, SSRF-guarded per call, and error-sanitised so no key or prompt escapes.
- **API + web**: connections (write-only keys), quotas, usage rollups, prompts
  (append-only versions), guardrail policies; an LLM tab and a Usage panel.

## Acceptance
1. echo + an OpenAI-compatible stub share one code path — asserted against a real
   socket, not a mocked SDK.
2. The ledger shows tokens + cost + model/provider/version per call. ✅
3. A low quota blocks with a clear error (e2e 17). ✅
4. A BSN-bearing prompt is stored redacted and the raw never persists — proven by
   inspecting what the provider received over the wire. ✅
5. `bsn` → `external` is hard-blocked with a guardrail event AND a chained audit
   entry. ✅

## Deviations from the plan, and why
- **Pipeline order** deviates from §5b's literal text: redaction runs before cache and
  provider. The literal order defeats its own acceptance criterion (ADR-0008 §1).
- **`nl_core_news_sm` is CC BY-SA 4.0, not MIT** as this plan first recorded. The §3.1
  gate caught it; OSAIP does not redistribute the model (ADR-0009). CC BY-SA was NOT
  added to the allowlist — the artifact is excluded by name, so baking it into a
  shipped image still fails.
- **tiktoken** is used for estimates as planned, but the characters-per-token fallback
  is retained: tiktoken fetches its BPE file on first use, which an air-gapped install
  cannot do.
- **`/v1/stream`** remains deferred (3b/P4) with its post-guardrail design.

## Defects found and fixed during the phase
A five-lens adversarial review raised 44 findings; 10 were adversarially verified and 6
were real, all fixed with named regression tests: a post-guardrail rejection that
skipped the ledger and stranded a quota hold; a BSN regex that missed the standard
Dutch separator format; a check-then-insert race on `traces`; a quota lookup that
silently dropped one of two budgets on a scope; and missing indexes that made every
scoped quota check scan the ledger while holding an advisory lock.

Found by tests rather than review: a keyless connection reported as a RETRYABLE
outage; LiteLLM's synthesised zero `usage` recorded as an exact measurement; a
`problem_response` that could not serialise a validation error (500 instead of 422,
latent API-wide); `secrets.project_id` NOT NULL making a global connection unable to
hold a key; a quotas API requiring a UUID the API never hands out; and a Usage panel
that rebuilt its query key every render, hammering `/usage` in a loop.

## New deps (§3.1)
litellm==1.95.0 MIT (pinned exact, wrapped, imported only in apps/mesh — CI grep-gated)
· tiktoken MIT (estimates only) · presidio-analyzer==2.2.362 MIT as an OPTIONAL extra
· spacy MIT. presidio-anonymizer was added then removed: unused, and its
`cryptography <44.1` cap pulled in four CVEs.

## Migrations
0004 (mesh tables) · 0005 (quota-scope indexes) · 0006 (platform-level secrets).

## Slices
0 plan+ADR-0008 · 1 migration 0004+mesh skeleton+echo+cost+SSRF+grep-gate · 2 ledger+
traces/spans+audit storage+cache · 3 quotas reserve/settle+usage rollup · 4 guardrails+
§5d+CP-11 (+4b Presidio/ADR-0009) · 5 LiteLLM+OpenAI stub · 6 API surface · 7 web ·
8 e2e 16/17+seed v3+docs+summary.

## Carried into 3b
LLM recipes in the Flow, Prompt Studio, promote-to-recipe, the spec §7 Phase 3 AC e2e,
`/v1/stream`, hybrid `/search` embeddings, SIEM/CEF export. Also: 30 of the review's 44
findings were never verified (the workflow capped verification at the 10 most severe and
logged the rest) — they are unexamined, not cleared.
