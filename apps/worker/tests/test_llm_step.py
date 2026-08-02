"""Row-level LLM execution: cancellation, checkpointing, ordering, partial failure.

These are the properties the SYNC step path gets for free and this one does not, so
each is asserted rather than assumed (ADR-0010 §2, §6).
"""

import uuid
from typing import Any

import pytest

from osaip_api.mesh_client import MeshCallFailed
from osaip_engine.llm_recipes import compile_llm_recipe
from osaip_worker import llm_step
from osaip_worker.llm_step import RowResult, StepAborted, StepCancelled, run_llm_rows

PLAN = compile_llm_recipe("llm_prompt", {"template": "Say {word}"}, ["word"])
ROWS = [{"word": f"w{i}"} for i in range(10)]


def _ids() -> dict[str, Any]:
    return {
        "connection_id": uuid.uuid4(),
        "model": "echo-1",
        "project_id": uuid.uuid4(),
        "user_id": None,
        "job_id": uuid.uuid4(),
        "job_step_id": uuid.uuid4(),
        "trace_id": uuid.uuid4(),
        "max_classification": "none",
        "purpose": "build",
    }


async def _never_cancelled() -> bool:
    return False


@pytest.fixture
def fake_mesh(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Records every call and answers deterministically. Patched on the module under
    test, so the real client's signature still has to match."""
    calls: list[dict[str, Any]] = []

    async def _call(settings: Any, **kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        word = kwargs["messages"][1]["content"]
        return {
            "content": f"answer:{kwargs['row_key']}:{len(word)}",
            "cost_micros": 3,
            "tokens_in": 2,
            "tokens_out": 1,
        }

    monkeypatch.setattr(llm_step, "call_mesh", _call)
    return calls


# ── ordering and attribution ────────────────────────────────────────────────────


async def test_output_order_follows_input_order(fake_mesh: list[dict[str, Any]]) -> None:
    """Bounded concurrency finishes rows out of order; a rebuild must still produce the
    same dataset."""
    outcome = await run_llm_rows(
        settings=object(), plan=PLAN, rows=ROWS, is_cancelled=_never_cancelled, **_ids()
    )
    assert [r.index for r in outcome.results] == list(range(10))
    assert outcome.results[3].output == "answer:3:" + str(
        len(fake_mesh[0]["messages"][1]["content"])
    )


async def test_every_call_carries_per_row_attribution(fake_mesh: list[dict[str, Any]]) -> None:
    """§6.3(7): a generated cell must be traceable to the job, step and row."""
    ids = _ids()
    await run_llm_rows(
        settings=object(), plan=PLAN, rows=ROWS[:3], is_cancelled=_never_cancelled, **ids
    )
    for index, call in enumerate(sorted(fake_mesh, key=lambda c: int(c["row_key"]))):
        assert call["job_id"] == ids["job_id"]
        assert call["job_step_id"] == ids["job_step_id"]
        assert call["trace_id"] == ids["trace_id"]
        assert call["row_key"] == str(index)


async def test_row_key_is_an_ordinal_not_a_cell_value(fake_mesh: list[dict[str, Any]]) -> None:
    """row_key is the one per-row field that bypasses redaction, and it is exported to a
    SIEM — so it must never carry data from the row."""
    rows = [{"word": "111222333"}, {"word": "jan@example.nl"}]
    await run_llm_rows(
        settings=object(), plan=PLAN, rows=rows, is_cancelled=_never_cancelled, **_ids()
    )
    keys = {call["row_key"] for call in fake_mesh}
    assert keys == {"0", "1"}


async def test_the_declared_classification_is_passed_through(
    fake_mesh: list[dict[str, Any]],
) -> None:
    ids = _ids()
    ids["max_classification"] = "bijzonder"
    await run_llm_rows(
        settings=object(), plan=PLAN, rows=ROWS[:1], is_cancelled=_never_cancelled, **ids
    )
    assert fake_mesh[0]["max_classification"] == "bijzonder"


# ── partial failure (ADR-0010 §6) ───────────────────────────────────────────────


async def test_a_failed_row_is_a_gap_not_a_failed_build(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _call(settings: Any, **kwargs: Any) -> dict[str, Any]:
        if kwargs["row_key"] == "2":
            raise MeshCallFailed(status=502, detail="provider hiccup", slug="provider-failed")
        return {"content": "ok", "cost_micros": 1}

    monkeypatch.setattr(llm_step, "call_mesh", _call)
    outcome = await run_llm_rows(
        settings=object(), plan=PLAN, rows=ROWS[:4], is_cancelled=_never_cancelled, **_ids()
    )
    assert outcome.rows == 4
    assert outcome.failed_rows == 1
    failed = outcome.results[2]
    assert failed.output is None
    assert failed.error == "provider hiccup"
    # The other rows survived — one hiccup must not discard an expensive run.
    assert [r.output for r in outcome.results if r.error is None] == ["ok", "ok", "ok"]


@pytest.mark.parametrize("slug", ["quota-exceeded", "residency-blocked"])
async def test_a_budget_or_sovereignty_refusal_aborts_the_step(
    monkeypatch: pytest.MonkeyPatch, slug: str
) -> None:
    """Neither is transient; continuing would only burn budget against a wall."""

    async def _call(settings: Any, **kwargs: Any) -> dict[str, Any]:
        raise MeshCallFailed(status=429, detail="out of budget", slug=slug)

    monkeypatch.setattr(llm_step, "call_mesh", _call)
    with pytest.raises(StepAborted) as excinfo:
        await run_llm_rows(
            settings=object(), plan=PLAN, rows=ROWS, is_cancelled=_never_cancelled, **_ids()
        )
    assert excinfo.value.slug == slug


# ── cancellation ────────────────────────────────────────────────────────────────


async def test_cancel_stops_the_loop_between_batches(fake_mesh: list[dict[str, Any]]) -> None:
    """The sync path's DuckDB interrupt does nothing to an HTTP loop, so this is the
    only thing making an expensive build stoppable."""
    seen = {"checks": 0}

    async def _cancelled() -> bool:
        seen["checks"] += 1
        return seen["checks"] > 1  # allow the first batch, cancel before the second

    with pytest.raises(StepCancelled):
        await run_llm_rows(
            settings=object(),
            plan=PLAN,
            rows=ROWS,
            is_cancelled=_cancelled,
            checkpoint_every=2,
            **_ids(),
        )
    # Stopped early rather than finishing all ten rows.
    assert len(fake_mesh) == 2


async def test_a_cancelled_build_keeps_what_it_already_paid_for(
    fake_mesh: list[dict[str, Any]],
) -> None:
    saved: list[RowResult] = []

    async def _save(batch: Any) -> None:
        saved.extend(batch)

    async def _cancelled() -> bool:
        return len(saved) >= 4

    with pytest.raises(StepCancelled):
        await run_llm_rows(
            settings=object(),
            plan=PLAN,
            rows=ROWS,
            is_cancelled=_cancelled,
            save_checkpoint=_save,
            checkpoint_every=2,
            **_ids(),
        )
    assert len(saved) == 4  # checkpointed before the cancel took effect


# ── checkpointing (ADR-0010 §2) ─────────────────────────────────────────────────


async def test_a_resumed_build_does_not_re_bill_completed_rows(
    fake_mesh: list[dict[str, Any]],
) -> None:
    """P2's atomic write plus the requeue sweeper would otherwise re-bill the same step
    up to three times — a build dying at 90% would restart from zero and pay again."""

    async def _load() -> dict[int, RowResult]:
        return {i: RowResult(index=i, output="from-checkpoint", cost_micros=99) for i in range(6)}

    outcome = await run_llm_rows(
        settings=object(),
        plan=PLAN,
        rows=ROWS,
        is_cancelled=_never_cancelled,
        load_checkpoint=_load,
        **_ids(),
    )
    assert outcome.resumed_rows == 6
    assert len(fake_mesh) == 4  # only the remaining rows were called
    assert outcome.rows == 10  # but the output is complete
    assert outcome.results[0].output == "from-checkpoint"
    assert outcome.results[9].output.startswith("answer:9")


async def test_checkpointed_rows_keep_their_place_in_the_output(
    fake_mesh: list[dict[str, Any]],
) -> None:
    """Resuming must not reorder: a gap in the middle is filled in place."""

    async def _load() -> dict[int, RowResult]:
        return {2: RowResult(index=2, output="old"), 7: RowResult(index=7, output="old")}

    outcome = await run_llm_rows(
        settings=object(),
        plan=PLAN,
        rows=ROWS,
        is_cancelled=_never_cancelled,
        load_checkpoint=_load,
        **_ids(),
    )
    assert [r.index for r in outcome.results] == list(range(10))
    assert outcome.results[2].output == "old"
    assert outcome.results[7].output == "old"


async def test_cost_is_summed_across_resumed_and_new_rows(
    fake_mesh: list[dict[str, Any]],
) -> None:
    async def _load() -> dict[int, RowResult]:
        return {0: RowResult(index=0, output="x", cost_micros=100)}

    outcome = await run_llm_rows(
        settings=object(),
        plan=PLAN,
        rows=ROWS[:3],
        is_cancelled=_never_cancelled,
        load_checkpoint=_load,
        **_ids(),
    )
    assert outcome.cost_micros == 100 + 3 + 3  # resumed + two fresh calls


# ── concurrency ─────────────────────────────────────────────────────────────────


async def test_concurrency_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    """A build must not saturate a provider — or a budget — in seconds."""
    import asyncio

    live = {"now": 0, "peak": 0}

    async def _call(settings: Any, **kwargs: Any) -> dict[str, Any]:
        live["now"] += 1
        live["peak"] = max(live["peak"], live["now"])
        await asyncio.sleep(0.01)
        live["now"] -= 1
        return {"content": "ok", "cost_micros": 0}

    monkeypatch.setattr(llm_step, "call_mesh", _call)
    await run_llm_rows(
        settings=object(),
        plan=PLAN,
        rows=[{"word": "x"} for _ in range(20)],
        is_cancelled=_never_cancelled,
        concurrency=3,
        **_ids(),
    )
    assert live["peak"] <= 3
