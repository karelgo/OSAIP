"""Ledger, audit storage, and trace/span writes.

The audit-mode matrix is the compliance-critical part: `redacted` (the default) must
leave no raw copy behind, `full` keeps both, `off` stores no text at all.
"""

import datetime
import uuid
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from osaip_api.models import LlmCall, LlmCallMessage, Project, Span, Trace
from osaip_mesh.ledger import LedgerEntry, ensure_trace, record_call, record_span
from osaip_mesh.providers.base import Message
from osaip_shared.ids import new_id


async def _project(session: AsyncSession) -> Project:
    project = Project(
        id=new_id(), key=f"l{uuid.uuid4().hex[:8]}", name="ledger", storage_prefix="p"
    )
    session.add(project)
    await session.flush()
    return project


def _entry(**overrides: Any) -> LedgerEntry:
    defaults: dict[str, Any] = {
        "provider": "echo",
        "model": "echo-1",
        "purpose": "general",
        "tokens_in": 10,
        "tokens_out": 5,
        "cost_micros": 1234,
        "currency": "EUR",
        "latency_ms": 42,
    }
    defaults.update(overrides)
    return LedgerEntry(**defaults)


REDACTED = [Message(role="user", content="my number is <BSN>")]
RAW = [Message(role="user", content="my number is 111222333")]


async def test_redacted_mode_stores_no_raw_copy(mesh_session: AsyncSession) -> None:
    """AC-4: the raw text never persists under the default audit mode."""
    call = await record_call(
        mesh_session,
        _entry(),
        messages_redacted=REDACTED,
        messages_raw=RAW,
        audit_mode="redacted",
    )
    await mesh_session.commit()

    rows = (
        (
            await mesh_session.execute(
                select(LlmCallMessage).where(LlmCallMessage.call_id == call.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].content_redacted == "my number is <BSN>"
    assert rows[0].content_raw is None
    assert "111222333" not in (rows[0].content_redacted or "")


async def test_full_mode_keeps_both_copies(mesh_session: AsyncSession) -> None:
    call = await record_call(
        mesh_session, _entry(), messages_redacted=REDACTED, messages_raw=RAW, audit_mode="full"
    )
    await mesh_session.commit()
    row = (
        await mesh_session.execute(select(LlmCallMessage).where(LlmCallMessage.call_id == call.id))
    ).scalar_one()
    assert row.content_redacted == "my number is <BSN>"
    assert row.content_raw == "my number is 111222333"


async def test_full_mode_skips_the_raw_copy_when_nothing_was_redacted(
    mesh_session: AsyncSession,
) -> None:
    """No second copy of text that redaction did not touch."""
    same = [Message(role="user", content="hello")]
    call = await record_call(
        mesh_session, _entry(), messages_redacted=same, messages_raw=same, audit_mode="full"
    )
    await mesh_session.commit()
    row = (
        await mesh_session.execute(select(LlmCallMessage).where(LlmCallMessage.call_id == call.id))
    ).scalar_one()
    assert row.content_raw is None


async def test_off_mode_stores_no_message_rows(mesh_session: AsyncSession) -> None:
    call = await record_call(
        mesh_session, _entry(), messages_redacted=REDACTED, messages_raw=RAW, audit_mode="off"
    )
    await mesh_session.commit()
    count = (
        await mesh_session.execute(
            select(func.count())
            .select_from(LlmCallMessage)
            .where(LlmCallMessage.call_id == call.id)
        )
    ).scalar_one()
    assert count == 0
    # The call itself is still ledgered — 'off' hides the text, not the usage.
    assert (await mesh_session.get(LlmCall, call.id)) is not None


async def test_ledger_row_carries_full_attribution(mesh_session: AsyncSession) -> None:
    """§6.3(7): a produced cell must be traceable to the job/step/row that made it."""
    project = await _project(mesh_session)
    job_id, step_id = new_id(), new_id()
    call = await record_call(
        mesh_session,
        _entry(
            project_id=project.id,
            job_id=job_id,
            job_step_id=step_id,
            row_key="row-17",
            model_version="echo-1@echo-1",
            request_hash="a" * 64,
        ),
        messages_redacted=REDACTED,
        audit_mode="redacted",
    )
    await mesh_session.commit()
    stored = await mesh_session.get(LlmCall, call.id)
    assert stored is not None
    assert (stored.job_id, stored.job_step_id, stored.row_key) == (job_id, step_id, "row-17")
    assert stored.provider == "echo"
    assert stored.model_version == "echo-1@echo-1"
    assert stored.cost_micros == 1234
    assert stored.currency == "EUR"


async def test_message_sequence_is_preserved(mesh_session: AsyncSession) -> None:
    messages = [
        Message(role="system", content="you are helpful"),
        Message(role="user", content="hi"),
        Message(role="assistant", content="hello"),
    ]
    call = await record_call(
        mesh_session, _entry(), messages_redacted=messages, audit_mode="redacted"
    )
    await mesh_session.commit()
    rows = (
        (
            await mesh_session.execute(
                select(LlmCallMessage)
                .where(LlmCallMessage.call_id == call.id)
                .order_by(LlmCallMessage.seq)
            )
        )
        .scalars()
        .all()
    )
    assert [(r.seq, r.role) for r in rows] == [(0, "system"), (1, "user"), (2, "assistant")]


async def test_ensure_trace_creates_once_and_reuses(mesh_session: AsyncSession) -> None:
    project = await _project(mesh_session)
    first = await ensure_trace(mesh_session, None, root_kind="manual", project_id=project.id)
    again = await ensure_trace(mesh_session, first, root_kind="manual", project_id=project.id)
    await mesh_session.commit()
    assert first == again
    count = (
        await mesh_session.execute(
            select(func.count()).select_from(Trace).where(Trace.trace_id == first)
        )
    ).scalar_one()
    assert count == 1


async def test_ensure_trace_honours_a_caller_supplied_id(mesh_session: AsyncSession) -> None:
    """A build step owns the trace; the mesh must nest under it, not start its own."""
    supplied = new_id()
    returned = await ensure_trace(mesh_session, supplied, root_kind="recipe")
    await mesh_session.commit()
    assert returned == supplied
    assert (await mesh_session.get(Trace, supplied)) is not None


async def test_spans_roll_up_onto_the_trace(mesh_session: AsyncSession) -> None:
    trace_id = await ensure_trace(mesh_session, None, root_kind="manual")
    t0 = datetime.datetime.now(datetime.UTC)
    t1 = t0 + datetime.timedelta(milliseconds=25)
    for cost in (100, 250):
        await record_span(
            mesh_session,
            trace_id=trace_id,
            name="echo:echo-1",
            started_at=t0,
            finished_at=t1,
            tokens=15,
            cost_micros=cost,
        )
    await mesh_session.commit()
    trace = await mesh_session.get(Trace, trace_id)
    assert trace is not None
    assert trace.span_count == 2
    assert trace.total_cost_micros == 350
    spans = (
        (await mesh_session.execute(select(Span).where(Span.trace_id == trace_id))).scalars().all()
    )
    assert {s.kind for s in spans} == {"llm"}


@pytest.mark.parametrize("mode", ["redacted", "full", "off"])
async def test_every_audit_mode_still_writes_the_ledger(
    mesh_session: AsyncSession, mode: str
) -> None:
    """Usage accounting is independent of how much text is retained."""
    call = await record_call(
        mesh_session, _entry(), messages_redacted=REDACTED, messages_raw=RAW, audit_mode=mode
    )
    await mesh_session.commit()
    assert (await mesh_session.get(LlmCall, call.id)) is not None
