"""Row-level LLM execution (ADR-0010 §2, §6).

Every other recipe step is a synchronous closure handed to a thread pool, because it is
CPU-bound DuckDB work. This one is the opposite — a loop of network calls — so it runs
as a coroutine on the event loop, where cancellation and concurrency actually work.

Three properties this module exists to guarantee, none of which the sync path needs:

1. **Cancel means cancel.** The sync path's only lever is a DuckDB `interrupt()`, which
   does nothing to an in-flight HTTP request. Here the loop checks the job's cancel flag
   at every batch boundary, so a 100k-row build stops in seconds rather than finishing.
2. **Rows already paid for stay paid for.** Completed batches are checkpointed to object
   storage. Without that, P2's atomic per-version write plus the requeue sweeper would
   re-bill the same step up to three times: a build dying at 90% would restart from zero
   and pay again.
3. **Output order is the input order**, independent of completion order. Bounded
   concurrency means rows finish out of order; the writer reassembles by row index, so a
   rebuild with the same inputs produces the same dataset.
"""

import asyncio
import json
import logging
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from osaip_api.mesh_client import MeshCallFailed, call_mesh
from osaip_engine.llm_recipes import LlmPlan

log = logging.getLogger("osaip.worker.llm")

# How many rows are in flight at once. Small on purpose: a build must not saturate a
# provider (or a budget) in seconds, and the mesh's per-scope budget lock serialises
# anyway. Raising this trades provider goodwill for wall-clock.
DEFAULT_CONCURRENCY = 4

# Rows per checkpoint. Larger means fewer writes; smaller means less re-billed work
# after a crash. 200 rows of a cheap model is cents.
CHECKPOINT_EVERY = 200

# Problems that mean "stop", not "skip this row". Continuing past these only burns
# budget against a wall (ADR-0010 §6).
FATAL_SLUGS = frozenset({"quota-exceeded", "residency-blocked", "not-found", "unauthenticated"})


class StepCancelled(Exception):
    """The job was cancelled between batches."""


class StepAborted(Exception):
    """A fatal, non-transient refusal — budget or sovereignty. Carries text safe to log."""

    def __init__(self, reason: str, *, slug: str | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.slug = slug


@dataclass
class RowResult:
    index: int
    output: str | None = None
    error: str | None = None
    cost_micros: int = 0
    tokens_in: int = 0
    tokens_out: int = 0

    def as_record(self) -> dict[str, Any]:
        return {
            "_osaip_row": self.index,
            "output": self.output,
            "error": self.error,
            "cost_micros": self.cost_micros,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
        }


@dataclass
class StepOutcome:
    results: list[RowResult] = field(default_factory=list)
    failed_rows: int = 0
    resumed_rows: int = 0
    cost_micros: int = 0

    @property
    def rows(self) -> int:
        return len(self.results)


CheckpointLoad = Callable[[], Awaitable[dict[int, RowResult]]]
CheckpointSave = Callable[[Sequence[RowResult]], Awaitable[None]]


async def run_llm_rows(
    *,
    settings: Any,
    plan: LlmPlan,
    rows: list[dict[str, Any]],
    connection_id: uuid.UUID,
    model: str,
    project_id: uuid.UUID,
    user_id: uuid.UUID | None,
    job_id: uuid.UUID,
    job_step_id: uuid.UUID,
    trace_id: uuid.UUID,
    max_classification: str,
    purpose: str,
    is_cancelled: Callable[[], Awaitable[bool]],
    load_checkpoint: CheckpointLoad | None = None,
    save_checkpoint: CheckpointSave | None = None,
    concurrency: int = DEFAULT_CONCURRENCY,
    checkpoint_every: int = CHECKPOINT_EVERY,
    on_progress: Callable[[int, int], None] | None = None,
) -> StepOutcome:
    """Run `plan` over `rows`, resuming anything already checkpointed."""
    done: dict[int, RowResult] = await load_checkpoint() if load_checkpoint else {}
    outcome = StepOutcome(resumed_rows=len(done))
    if done:
        log.info("resuming llm step: %s of %s rows already done", len(done), len(rows))

    pending = [index for index in range(len(rows)) if index not in done]
    semaphore = asyncio.Semaphore(max(1, concurrency))

    for batch_start in range(0, len(pending), checkpoint_every):
        # Between batches, not mid-flight: a cancelled build stops in seconds without
        # abandoning calls that are already being paid for.
        if await is_cancelled():
            raise StepCancelled()

        batch = pending[batch_start : batch_start + checkpoint_every]
        completed = await asyncio.gather(
            *(
                _one_row(
                    settings=settings,
                    plan=plan,
                    row=rows[index],
                    index=index,
                    semaphore=semaphore,
                    connection_id=connection_id,
                    model=model,
                    project_id=project_id,
                    user_id=user_id,
                    job_id=job_id,
                    job_step_id=job_step_id,
                    trace_id=trace_id,
                    max_classification=max_classification,
                    purpose=purpose,
                )
                for index in batch
            )
        )
        for result in completed:
            done[result.index] = result
        if save_checkpoint:
            await save_checkpoint(completed)
        if on_progress:
            on_progress(len(done), len(rows))

    # Reassembled by INDEX, not by completion order — bounded concurrency finishes rows
    # out of order, and a rebuild must produce the same dataset.
    outcome.results = [done[index] for index in range(len(rows)) if index in done]
    outcome.failed_rows = sum(1 for r in outcome.results if r.error is not None)
    outcome.cost_micros = sum(r.cost_micros for r in outcome.results)
    return outcome


async def _one_row(
    *,
    settings: Any,
    plan: LlmPlan,
    row: dict[str, Any],
    index: int,
    semaphore: asyncio.Semaphore,
    connection_id: uuid.UUID,
    model: str,
    project_id: uuid.UUID,
    user_id: uuid.UUID | None,
    job_id: uuid.UUID,
    job_step_id: uuid.UUID,
    trace_id: uuid.UUID,
    max_classification: str,
    purpose: str,
) -> RowResult:
    async with semaphore:
        try:
            result = await call_mesh(
                settings,
                connection_id=connection_id,
                model=model,
                messages=plan.messages(row),
                project_id=project_id,
                user_id=user_id,
                purpose=purpose,
                max_classification=max_classification,
                max_tokens=plan.max_tokens,
                # Attribution the ledger already stores, and what makes §6.3(7)
                # ("why is this cell what it is?") answerable per row. `row_key` is the
                # ORDINAL, never a value from the row — it is the one per-row field
                # that bypasses redaction, and it is exported to a SIEM.
                job_id=job_id,
                job_step_id=job_step_id,
                trace_id=trace_id,
                row_key=str(index),
                output_schema=plan.output_schema,
            )
        except MeshCallFailed as exc:
            if exc.slug in FATAL_SLUGS:
                raise StepAborted(exc.detail, slug=exc.slug) from exc
            # Everything else is this row's problem, not the build's (ADR-0010 §6).
            return RowResult(index=index, error=exc.detail)

    content = str(result.get("content") or "")
    return RowResult(
        index=index,
        output=_coerce(plan, content),
        cost_micros=int(result.get("cost_micros") or 0),
        tokens_in=int(result.get("tokens_in") or 0),
        tokens_out=int(result.get("tokens_out") or 0),
    )


def _coerce(plan: LlmPlan, content: str) -> str:
    """Whatever ends up in the column. Extract keeps JSON as text — typing it into real
    columns needs a schema-wide pass, which belongs with the writer, not here."""
    if plan.kind == "llm_classify":
        # The mesh already enforced the enum via the output schema; strip stray
        # whitespace or quoting a model may add around a single label.
        return content.strip().strip('"').strip()
    if plan.kind == "llm_extract":
        try:
            return json.dumps(json.loads(content), sort_keys=True, separators=(",", ":"))
        except json.JSONDecodeError:
            return content
    return content
