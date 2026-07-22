import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from osaip_api.audit import GENESIS_HASH, verify_chain, write_audit


async def _append(session: AsyncSession, action: str, **kwargs: object) -> None:
    await write_audit(
        session,
        actor_id=None,
        project_id=None,
        action=action,
        object_kind="test",
        details={"note": action, "n": 1, "nested": {"unicode": "café ✓", "flag": True}},
        **kwargs,  # type: ignore[arg-type]
    )
    await session.commit()


async def test_chain_grows_and_verifies(db_session: AsyncSession) -> None:
    for index in range(5):
        await _append(db_session, f"test.action-{index}")
    result = await verify_chain(db_session, batch_size=2)
    assert result.ok, result
    assert result.checked >= 5


async def test_first_row_links_to_genesis(db_session: AsyncSession) -> None:
    first = await db_session.execute(
        text("SELECT prev_hash FROM audit_log ORDER BY seq ASC LIMIT 1")
    )
    assert first.scalar_one() == GENESIS_HASH


async def test_tamper_is_detected(db_session: AsyncSession) -> None:
    await _append(db_session, "test.pre-tamper")
    # Simulate a privileged attacker: disable the append-only trigger, rewrite a
    # detail, re-enable. verify_chain must flag the row from a FRESH read.
    await db_session.execute(
        text("ALTER TABLE audit_log DISABLE TRIGGER audit_log_no_update_delete")
    )
    await db_session.execute(
        text(
            "UPDATE audit_log SET details = jsonb_set(details, '{note}', '\"tampered\"') "
            "WHERE seq = (SELECT max(seq) FROM audit_log)"
        )
    )
    await db_session.execute(
        text("ALTER TABLE audit_log ENABLE TRIGGER audit_log_no_update_delete")
    )
    await db_session.commit()

    result = await verify_chain(db_session)
    assert not result.ok
    assert result.reason == "row_hash mismatch"
    assert result.first_bad_seq is not None

    # Repair for later tests in this session-scoped DB: restore the original value.
    await db_session.execute(
        text("ALTER TABLE audit_log DISABLE TRIGGER audit_log_no_update_delete")
    )
    await db_session.execute(
        text(
            "UPDATE audit_log SET details = jsonb_set(details, '{note}', '\"test.pre-tamper\"') "
            "WHERE seq = (SELECT max(seq) FROM audit_log)"
        )
    )
    await db_session.execute(
        text("ALTER TABLE audit_log ENABLE TRIGGER audit_log_no_update_delete")
    )
    await db_session.commit()
    assert (await verify_chain(db_session)).ok


async def test_update_delete_truncate_blocked(db_session: AsyncSession) -> None:
    await _append(db_session, "test.append-only")
    for statement in (
        "UPDATE audit_log SET action = 'x' WHERE seq = (SELECT max(seq) FROM audit_log)",
        "DELETE FROM audit_log WHERE seq = (SELECT max(seq) FROM audit_log)",
        "TRUNCATE audit_log",
    ):
        with pytest.raises(Exception, match="append-only"):
            await db_session.execute(text(statement))
        await db_session.rollback()


async def test_details_reject_floats(db_session: AsyncSession) -> None:
    with pytest.raises(ValueError, match="floats"):
        await write_audit(
            db_session,
            actor_id=None,
            project_id=None,
            action="test.float",
            object_kind="test",
            details={"ratio": 0.5},
        )
    await db_session.rollback()
