# ADR-0010: LLM recipe execution — redaction, the async step seam, budgets and provenance

- **Status**: accepted
- **Date**: 2026-08-02
- **Deciders**: karel goense (approved 2026-08-02)
- **Supersedes**: nothing. **Extends**: ADR-0007 (jobs/recipes/sandbox), ADR-0008 (LLM Mesh).
- **Plan**: `docs/plans/phase-3b.md` (v2, post-verification)

## Context

Phase 3a built the mesh — the choke point every model call passes through, with the
ledger, budgets, guardrails and the CP-11 gate — but nothing in the Flow can call it.
Phase 3b adds the callers: four LLM recipe kinds executed **per row** over a dataset,
plus Prompt Studio.

Per-row execution changes the risk profile more than the feature list suggests. It is
the first time OSAIP:

- sends possibly-personal data to a model **at scale** (a build is 100k calls, not one),
- spends **real money per build** rather than per click,
- **generates content that persists** — a model's output becomes a dataset column that
  propagates downstream and gets exported,
- takes a **user-editable config field carrying an arbitrary connection UUID** into the
  mesh.

A 4-lens adversarial review of the phase plan returned 69 findings / 23 blockers. Four
of them invalidated the plan's architecture rather than its wording, and are decided
here. The rest are folded into the plan's slices.

## Decision 1 — Redaction wins; LLM recipes are for non-personal columns

**The problem.** 3a's baseline PII redaction is deliberately non-removable (BIO2 8.12):
`run_pre_stage` → `redact()` runs on every message and `PolicyConfig.redact_pii` is not
readable from the policy document. So an `llm_summarize` over a column of customer
emails sends `<EMAIL>` to the model and summarises placeholders. The feature and the
guarantee collide head-on.

**Decision.** The guarantee wins, unqualified. LLM recipes target non-personal columns.

Two alternatives were considered and declined:

- **Reversible pseudonymisation** (stable tokens out, restored on the way back)
  preserves utility, but it creates a token map that is itself sensitive, adds a leak
  surface on every partial response, and re-opens a property 3a closed on purpose.
- **A per-connection opt-out for `local` residency** is narrower, but it still converts
  a documented "not configurable" guarantee into a configurable one — which is exactly
  the sentence a DPIA reviewer will quote back.

Neither is worth it for a capability that has an honest alternative: say so clearly.

**Consequence, and the thing that makes this liveable.** A limit nobody is told about is
a bug report. The recipe preview therefore reports when baseline redaction fired on a
sampled row, naming the kinds detected (`bsn`, `iban`, `email`, `phone`) and their
counts — never the values. A user meets the limit as a sentence, not as output that
summarises `<EMAIL>`.

This is revisitable: if pseudonymisation is later wanted, it is an additive stage with
its own ADR, not a reversal of this one.

## Decision 2 — LLM steps get their own async seam; engine steps do not move

**The problem.** `_do_build()` is a **synchronous closure** handed to `run_engine`
(anyio thread offload), and the only cancellation lever is a DuckDB
`connection.interrupt()`. A per-row loop of HTTP calls to the mesh fits neither: it
cannot run inside a sync closure without blocking a pool slot for the whole build, and
`interrupt()` does nothing to an in-flight `httpx` request. An expensive LLM build would
therefore be **uncancellable**.

**Decision.** Add a second step path rather than converting the first. Engine steps keep
the sync/`run_engine` shape that Phase 2 tests and cancellation semantics depend on; LLM
steps run as a native async coroutine on the event loop, where the HTTP calls belong.

The async path carries three properties the sync one gets for free and this one does not:

- **Cooperative cancellation** — the row loop checks the existing `_cancel_requested`
  between rows and at every batch boundary, so cancel means cancel rather than "finish
  the 100k rows first".
- **Checkpointing** — completed rows are persisted per batch. P2's atomic per-version
  write plus the requeue sweeper can otherwise re-bill the same step up to **three
  times**: a build that dies at 90% would restart from zero and pay again.
- **Deterministic output ordering** independent of completion order, so a rebuild with
  the same inputs produces the same dataset. Bounded concurrency means rows finish out
  of order; the writer reassembles by row index, not by arrival.

## Decision 3 — Budgets reserve per step with batch top-ups, never per row

**The problem.** The plan's v1 said a build "reserves per row, not per build". Reading
`quotas.py`: `reserve()` takes a per-scope `pg_advisory_xact_lock` and recomputes a
window SUM over `llm_calls` + open reservations, then commits. Per row that (a)
serialises the entire build behind one lock, defeating the bounded concurrency it sits
inside, and (b) makes the locked aggregate grow with the ledger rows the build is
itself writing — superlinear in the number of rows.

**Decision.** Reserve once per step for the estimated total, then **top up in batches**
as the build proceeds, settling to actual at the end. One lock acquisition per batch.

The trade is deliberate: a large hold is briefly pessimistic against concurrent callers
on the same scope. That is the correct direction — a budget that is briefly too strict
refuses a call that could have run, while a budget that is too loose spends money that
cannot be recovered.

## Decision 4 — Generated columns are marked as generated (AI Act Art 50), in 3b

**The problem.** The plan originally deferred Art 50 content marking to Phase 4 "with
Answers". But 3b is the first place OSAIP *generates content at all*, and a generated
**dataset column** is materially worse than a chat answer: it persists, feeds downstream
recipes, is exported, and looks exactly like observed data to everyone who reads it
later.

**Decision.** Marking lands in 3b. A column produced by an LLM recipe is flagged in the
dataset schema, shown as such in the UI, and carried by lineage so a downstream reader
can tell derived-from-a-model from measured.

## Decision 5 — Connection authz is enforced in the mesh, not only in the API

**The problem.** `_load_connection` in the mesh filters on `id` + `status='active'`
only. The sole scope check lives in the API's project-scoped connection routes, which
neither the worker's build path nor the new Prompt Studio endpoints traverse. 3b is the
first phase where a user-editable config field carries an arbitrary connection UUID, so
a project editor who learns another project's connection id would get that project's
API key, model allowlist and budget.

**Decision.** Validate at recipe save **and** inside the mesh pipeline. Caller-side
validation is a usability affordance; the mesh check is the control. Spec §5b already
names "authz (project + connection permission)" as the pipeline's first step — this
makes the implementation match.

`ConnectionInfo` gains the owning project/scope so `run_pipeline` can compare it against
the declared `project_id`, which today is attribution metadata that nothing checks.

## Decision 6 — Partial failure yields a marked gap, not a lost build

A failed row produces a null output plus an error column, and the build succeeds. One
provider hiccup must not discard a run that has already been paid for.

A **quota block or a residency refusal aborts the step** instead: those are not
transient, and continuing would only burn budget against a wall.

The failed-row count surfaces in the run drawer, because a dataset with silent holes is
worse than a failed build — the whole point of continuing is that someone knows what
they got.

## Consequences

- LLM recipes are honest about what they cannot do, and say so at preview time.
- Two step execution paths exist in the executor. That is real complexity, justified by
  the fact that one is CPU-bound-in-a-thread and the other is IO-bound-on-the-loop.
- A build can be cancelled and can resume, so a large run is no longer all-or-nothing.
- Budget enforcement stays correct under concurrency without serialising builds.
- Generated data is distinguishable from observed data, permanently and downstream.
- Cross-project connection use is refused at the choke point, where it cannot be
  routed around.

## What this ADR does not decide

Pseudonymisation (revisitable, additive) · streaming and its post-guardrail design
(P4) · the embedding path, which has no implementation at all today and moves to P4
with KB/RAG · agent/tool execution (P6).
