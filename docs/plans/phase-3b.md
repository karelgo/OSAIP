# Phase 3b — LLM recipes & Prompt Studio (OSAIP) · v2 (post-verification)

## Context
Phase 3a built the mesh: the choke point every model call passes through, with the
ledger, budgets, guardrails and the CP-11 gate. Nothing in the Flow can call it yet.
3b closes that and lands spec §7 Phase 3's acceptance criteria.

A 4-lens review of the v1 draft returned 69 findings / 23 blockers. Several were not
wording problems — v1 asserted things about this codebase that are false, and collided
with a safety property 3a deliberately made non-negotiable. The corrections are folded
in below and the scope is cut accordingly.

**The four that changed the shape of this phase:**

1. **Baseline redaction rewrites the input.** `run_pre_stage` → `redact()` runs on every
   message and `PolicyConfig.redact_pii` cannot be switched off (BIO2 8.12, by design).
   So `llm_summarize` over a column of customer emails sends `<EMAIL>` to the model and
   summarises placeholders. **Decided (2026-08-02): accept and be explicit.** 3a's
   guarantee stays intact and unqualified; LLM recipes are for non-personal columns, and
   the UI says so when redaction fires on a preview row — a user learns the limit from a
   clear message, never from bad output.
2. **The executor has no async seam.** `_do_build()` is a synchronous closure handed to
   `run_engine` (thread offload), and the only cancellation lever is a DuckDB
   `interrupt()`. A per-row loop of HTTP calls fits neither: it cannot run there, and an
   expensive build could not be cancelled. This is its own slice, not a footnote.
3. **Per-row quota reservation does not work as imagined.** `reserve()` takes a
   per-scope `pg_advisory_xact_lock` and recomputes a window SUM over `llm_calls` +
   open reservations on every call. Per row, that serialises the build behind one lock
   and the locked SUM grows with the rows the build is itself writing — superlinear.
4. **`llm_extract` has nowhere to put its schema.** The `post` JSON-schema comes from
   the CONNECTION's guardrail policy; `CompleteIn` has no schema field. A per-recipe
   output schema needs a mesh API change.

## Scope
1. **Mesh additions** (small, first): a per-request `output_schema` on `POST
   /v1/complete` (merged with, never replacing, the connection policy's), and
   **connection authz inside the mesh** — the pipeline currently loads a connection by
   id alone, and 3b is the first phase where a user-editable config field carries an
   arbitrary connection UUID. Validated at recipe save AND in the mesh, so a caller-side
   miss cannot bypass it.
2. **One compiler, four modes** — `llm_prompt`, `llm_classify`, `llm_extract`,
   `llm_summarize`. The AC says "identical code path"; four near-copies is how that
   stops being true. Every interpolated cell goes through `untrusted_block()`, and the
   recipe preview reports when baseline redaction fired on a sampled row, so the
   non-personal-columns limit is discovered from a message rather than from output that
   summarises `<EMAIL>`.
3. **An async step seam in the executor** (`_do_build` stays sync for engine steps; LLM
   steps get an async path), with:
   - **cooperative cancellation** that actually interrupts a row loop,
   - **checkpointing** so a mid-build abort or a worker requeue does not throw away
     rows already paid for — P2's atomic write plus the requeue sweeper can otherwise
     re-bill the same step up to three times,
   - **bounded concurrency**, and deterministic output ordering independent of
     completion order,
   - **partial-failure semantics**: a failed row yields a null output plus an error
     column and the build succeeds; a quota block or a residency refusal aborts the step
     instead, because continuing would only burn budget. The failed-row count surfaces
     in the run drawer — a dataset with silent holes is worse than a failed build.
4. **Budgets that work per build**: reserve once per step for the estimated total, then
   top up in batches as it runs, settling to actual. One lock acquisition per batch, not
   per row.
5. **CP-1 propagation**: the compiler derives `max_classification` as the floor over the
   *interpolated columns* (`osaip_api.propagation.classification_floor` already exists),
   falling back to the dataset label. Never a hardcoded `none` — that would silently
   defeat CP-11 at the exact path where citizen data first reaches an external model.
6. **CP-2 purpose binding**: a build's purpose codes must be compatible with the
   connection's `purpose_codes`; incompatible is a refusal, not a warning.
7. **AI Act Art 50 provenance** — pulled INTO 3b from P4. 3b is the first place OSAIP
   *generates content*, and a generated dataset column persists, propagates downstream
   and gets exported in a way a chat answer does not. Generated columns are marked in
   the schema, shown in the UI, and carried by lineage.
8. **Cost preflight, enforced server-side.** Estimate rows × tokens × price before the
   build; an over-budget build is refused by the API, not merely warned about in the
   dialog. An unpriced model must NOT estimate to zero — it is reported as unknown and
   requires explicit confirmation.
9. **Prompt Studio**: prompts × models over a sample **hard-capped at 20 rows**,
   comparison table, promote → recipe. `purpose=studio`, never cached. 20 is enough to
   separate two prompts while keeping a 3×3 grid at 180 calls — experimenting must never
   produce a surprising bill.
10. **`row_key`**: defined as a non-identifying ordinal/hash — it is the one per-row
    field that bypasses redaction, and slice 7's SIEM export would carry it off-box.
11. **SIEM/CEF export** of audit + ledger (CP-7's Phase-3 half).

## Out of scope (recorded, with target)
**Hybrid `/search` embeddings — moved to Phase 4, with KB/RAG (decided 2026-08-02).**
The mesh has no embedding path at all: the `Provider` protocol exposes only
`complete()`, there is no `/v1/embed`, no embedding pricing, and no pgvector column or
backfill. That is phase-sized work rather than half a slice, and P4 needs it anyway — so
it gets built once, there.

Also out: Agents/tools + Trace Explorer (P6) · KB/RAG (P4) · semantic layer (P5) ·
red-team eval SET (P7) · `/v1/stream` (P4) · BSN pseudonymisation service (P5).

## Endpoints
`POST /v1/complete` gains `output_schema` (mesh) · `POST /projects/{key}/prompt-studio/run`
· `POST /projects/{key}/prompt-studio/promote` · `POST /projects/{key}/recipes/{id}/estimate`
· `GET /admin/export/audit?format=cef`.

## Tests
**engine**: one compiler across four modes; untrusted wrapping of every cell;
deterministic ordering under concurrency; schema-validated extract → typed columns.
**worker**: cancellation actually stops a row loop mid-build; a checkpointed build
resumes without re-billing; a requeue does not double-charge; partial failure yields a
row error, while a quota block or residency refusal aborts the step.
**mesh/api**: cross-project connection use is denied in BOTH the API and the mesh; a
`bsn`-labelled input column + an `external` connection aborts with the residency
problem; purpose-incompatible build refused; over-budget build refused server-side;
unpriced model does not estimate zero.
**e2e 18-20**: `18-llm-classify` (the spec AC: two connections, identical code path,
ledger shows tokens+cost) · `19-prompt-studio` (comparison renders, promote works) ·
`20-cost-and-cancel` (preflight refuses over budget; a running LLM build cancels) ·
axe on the new surfaces.

## Slices (1 commit each)
0. This plan + ADR-0010 (redaction-vs-LLM-input decision, execution model, checkpointing
   and reservation strategy, provenance marking, preflight).
1. Mesh: per-request `output_schema` + connection authz in the pipeline (+tests).
2. Engine: one compiler, four modes, untrusted wrapping, CP-1 floor derivation (+tests).
3. Executor: async step seam, cooperative cancel, checkpointing (+tests).
4. Budgets per step with batch top-up + server-side preflight (+tests).
5. Provenance marking (Art 50) + CP-2 purpose binding (+tests, migration 0007).
6. Prompt Studio API (+tests, gen-api).
7. Web: LLM recipe inspectors + preflight in the build dialog + provenance in the UI.
8. Web: Prompt Studio page + promote.
9. SIEM/CEF export.
10. e2e 18-20 + seed v4 + docs + CHANGELOG + phase summary (§9.4).

## Verification / DoD
`make ci` green including e2e 18-20, hermetic · the spec §7 Phase 3 AC asserted by named
tests · a build cannot start without a preflight, and cannot exceed budget · an LLM build
can be cancelled · no provider SDK outside `apps/mesh` · summary + stop (§9.4).

## Decisions taken (2026-08-02, user-approved)

1. **Redaction vs LLM input: accept and be explicit.** The non-removable baseline stays
   non-removable. LLM recipes target non-personal columns; when redaction fires on a
   preview row the UI says so plainly. No pseudonymisation, no per-connection opt-out —
   both would re-open a property 3a deliberately closed, and neither is worth that for a
   capability that has an honest alternative. Recorded in ADR-0010.
2. **Partial failure: a failed row yields null + an error column; the build succeeds.**
   One provider hiccup must not discard an expensive run. The gaps are made visible —
   the error column plus a failed-row count in the run drawer — because a dataset with
   silent holes is worse than a failed build.
3. **Prompt Studio sample: 20 rows, hard-capped.** Not user-raisable; a raisable default
   gets raised once and stays there.
4. **Hybrid `/search` embeddings: Phase 4, with KB/RAG.** The embedding path gets built
   once, where it is needed anyway.
