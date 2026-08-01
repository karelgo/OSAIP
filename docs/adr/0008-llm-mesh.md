# ADR-0008: The LLM Mesh — pipeline, cost, quotas, guardrails, sovereignty

Status: Accepted · 2026-07-29 · Phase 3a

Phase 3 begins the agentic arc with `apps/mesh`, the gateway every model call in the
platform must pass through (spec §5b: "No code path may call a provider SDK directly.
Ever."). A 4-lens adversarial review of the phase plan returned 98 findings (24
blockers); this ADR records the decisions that resolve them, and the one deliberate
deviation from a LOCKED ordering.

## 1. Pipeline order — and why redaction moves before the cache

Spec §5b specifies: authz → quota check → cache lookup → guardrails `pre` → provider →
guardrails `post` → ledger + audit + span. **We implement:**

```
authz → CP-11 residency gate → guardrails `pre` (redact) → quota reserve
      → cache lookup (on the REDACTED payload) → provider
      → guardrails `post` → settle (ledger + audit + span)
```

**Deviation (§9.6, deliberate):** redaction runs *before* the cache lookup and the
provider call. The literal order is unimplementable against its own acceptance
criterion — "PII in a test prompt is redacted in the stored audit" — because:

- a cache **hit** under the literal order never runs `pre`, so the audit for that call
  would store unredacted input; and
- the cache key would be computed over raw text, putting PII into `request_hash` and
  into every cache row.

Redacting first fixes both, and improves hit rates (two prompts differing only in a
person's name become one cache entry). The rest of the order is unchanged. Quota
*reserve* moves ahead of the cache so a blocked caller is rejected before any lookup;
a cache hit settles the reservation at zero cost.

## 2. Cost — integer micros, explicit currency

Prices live in a pinned `model_prices.json` in the repo (with a `verified_on` date),
never fetched at runtime. `cost_micros` is an **integer** (millionths of a currency
unit) with an explicit `currency` column (EUR); rounding is **half-up on the computed
total**, never truncation per token. An unknown model yields cost `0` plus a
`pricing_unknown` flag on the ledger row — the platform never guesses a price. Token
counts come from the provider when reported; a `tiktoken` fallback is allowed only
when a provider omits usage, and the row is flagged `tokens_estimated` (never
presented as exact).

## 3. Quotas — reserve/settle, not check-then-hope

A naive "sum the window, then call" races: N concurrent calls all pass the check and
collectively blow the budget. Instead:

1. **Reserve** (short txn): `pg_advisory_xact_lock(scope)` → sum the window
   *including outstanding reservations* → insert a reservation row sized by the
   request's `max_tokens` (worst case).
2. **Settle**: after the call, update the reservation to the actual cost (or zero on
   a cache hit / failure).

Concurrent calls therefore see each other's reservations and cannot overshoot.
Abandoned reservations (crashed caller) are swept by the worker after a timeout.
Warn → response header + notification. Block → `429` problem+json carrying the limit,
window, and current spend, with slug `quota-exceeded` — deliberately distinct from a
provider's own rate limit (`provider-rate-limited`), which is retryable and is not the
operator's budget.

## 4. Cache

Key = sha256 over (connection_id, project_id, model, **redacted** normalized messages,
params). `project_id` is in the key even for globally-scoped connections, so one
project's cached completions can never surface in another. TTL per connection;
expired rows are swept by the worker. Calls with `purpose=guardrail` (judge) or
`purpose=eval` are never cached — a cached judgement would silently freeze a
moderation decision. A cache hit still writes a full ledger row (`cache_hit=true`,
cost 0) so usage accounting stays complete.

## 5. Guardrails — a baseline that cannot be switched off

`packages/guardrails` exposes a stage protocol (`pre`/`post`) so NeMo Guardrails can
slot in later behind the same interface (ADR first, per §3.2).

- `pre`: deterministic regex first — **Dutch BSN with the 11-proef checksum**, IBAN
  (mod-97), email, phone — then **Presidio** (lazy-loaded engine, pinned Dutch
  `nl_core_news_sm` model, executed via `run_engine`'s thread offload because it is
  blocking), then a max-token check.
- `post`: judge-model moderation and a JSON-schema validator.

**The baseline PII-redaction policy applies to every connection.** A policy may add
rules; it may not remove the baseline (BIO2 8.12 data-leakage prevention — an operator
must not be able to disable redaction for a connection that egresses personal data).

Judge calls are themselves mesh calls, so they need a recursion guard: they carry
`purpose=guardrail` **and a depth counter**. A bare boolean is not a guard — a judge
whose own output is judged would loop; depth ≥ 1 skips post-moderation.

**English is not the corpus.** The Dutch model is the default precisely because this
platform targets Dutch public-sector data; an English-only NER would under-detect NL
names, addresses, and BSN contexts.

## 6. Prompt-injection posture (§5d, release-blocking per §8)

The mesh is where untrusted content meets an instruction-following model:

- **System prompts are assembled server-side** from the prompt registry. A client may
  select a prompt version; it may never supply the system role.
- **All untrusted content** (dataset cell values, retrieved chunks, tool output) is
  wrapped by a single documented `untrusted_block()` helper that tags and
  escape-neutralises it, and is passed as user-role content — never concatenated into
  the system prompt.
- A unit matrix of classic injection payloads asserts the embedded instruction is not
  followed.

The red-team *eval set* ships with the eval runner in Phase 7 (§10); the fixtures
arrive with Phase 3b's seed.

## 7. CP-11 sovereignty — at the choke point, fail-closed

The mesh is the first place personal data can leave the platform to a third-country
API, so the residency gate lives **in the mesh pipeline**, not in any one caller (a
caller-side gate is bypassed by every other caller — Prompt Studio, previews, agents).

- `llm_connections.data_residency` ∈ `local | eu | external`.
- Every caller must declare the **maximum CP-1 classification** of the payload it is
  sending. `bsn` / `bijzonder` / `bbn3` may route only to `local` connections.
- A violation is a hard block (403 problem+json) plus a `guardrail_events` row **and**
  an audit entry.
- A **missing declaration fails closed** — treated as `bijzonder`.

**Residency is operator-asserted metadata, not a technical guarantee.** Marking a
connection `eu` does not prove where the provider processes data; it records the
operator's assertion so the gate can act on it and an auditor can review it. The
platform enforces the policy, not the geography.

## 8. Ledger, audit, and retention

`llm_calls` carries the full §4 column set (including `trace_id`, `agent_id?`,
`session_id?`) **plus** `job_id? / job_step_id? / row_key?`, so a value produced by an
LLM is attributable to the build, step, and row that produced it — this is what makes
the §6.3(7) "why?" affordance reconstructable later.

Message content lives in `llm_call_messages`: the **redacted** variant always; the raw
variant only when the connection's `audit_mode=full`. `audit_mode=off` is
site-admin-only and setting it is itself audited.

Ledger rows are plain inserts in their **own short transaction** — deliberately
*outside* the hash-chained audit log's global advisory lock (ADR-0005), because
per-row LLM builds would otherwise serialize every mutation on the platform. Only
policy-relevant events (connection changes, residency blocks, audit-mode changes) go
into the chained audit.

`llm_calls`, `llm_call_messages`, and `spans` carry a **retention class of ≥ 6 months**
(CP-7; AI Act Art 26(6) deployer log-retention). The worker's prune never deletes
inside that window.

## 9. The echo provider

A built-in `echo` provider returns deterministic, token-counted responses with no
network access. It exists so CI and the acceptance suite are hermetic and free, and it
implements the *same* `Provider` protocol as LiteLLM — so "two connections, identical
code path" is genuinely exercised rather than special-cased. It is labelled as a mock
in the UI and **refuses any connection whose residency is not `local`**. Because echo
alone would never execute the LOCKED LiteLLM adapter, CI also runs a local
OpenAI-compatible stub server through the real LiteLLM path.

## 10. Dependencies and air-gap

`litellm` is pinned exact and wrapped behind our own API surface (§10: "pin the
version; wrap behind apps/mesh's own API; only enable the features listed"). The
spaCy model is installed **at image build from a pinned wheel** — no runtime download,
so an air-gapped deployment works and CI stays hermetic. Resolution verified:
presidio-analyzer 2.2.362 + spacy 3.8.14 + numpy 2.5.1 co-resolve with our pins.

## 11. mesh → osaip_api dependency

The mesh imports `osaip_api` models/Vault/events, exactly as the worker does. The
refactor trigger from ADR-0007 §8 still stands and now covers three consumers: before
Phase 8 scenario steps land, models/audit/events move to `packages/shared`.
