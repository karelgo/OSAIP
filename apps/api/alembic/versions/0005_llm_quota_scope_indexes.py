"""Index llm_calls on the columns quota checks filter by.

Quota enforcement sums the ledger per scope — project, user, connection or agent —
inside `pg_advisory_xact_lock`. Migration 0004 indexed only (project_id, ts), job_id and
trace_id, so a user-, connection- or agent-scoped budget check did a sequential scan of
the whole ledger WHILE HOLDING THE LOCK. On a per-row LLM build the ledger is the
fastest-growing table in the platform, so this degrades superlinearly: every call is
slower, and each one holds the scope's lock longer, so concurrent calls on the same
scope queue behind it.

Composite (scope, ts) rather than a bare scope index: every quota query is
`WHERE <scope> = ? AND ts >= ?`, and the usage rollups filter by ts too.

Revision ID: 0005
Revises: 0004
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index("ix_llm_calls_user_ts", "llm_calls", ["user_id", "ts"])
    op.create_index("ix_llm_calls_connection_ts", "llm_calls", ["connection_id", "ts"])
    op.create_index("ix_llm_calls_agent_ts", "llm_calls", ["agent_id", "ts"])
    # The reservation window sum filters (scope_type, scope_id, ts) AND settled_micros;
    # 0004's index stops at ts, so every reserve() re-reads settled rows it discards.
    op.create_index(
        "ix_quota_reservations_open",
        "quota_reservations",
        ["scope_type", "scope_id", "ts"],
        postgresql_where=sa.text("settled_micros IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_quota_reservations_open", table_name="quota_reservations")
    op.drop_index("ix_llm_calls_agent_ts", table_name="llm_calls")
    op.drop_index("ix_llm_calls_connection_ts", table_name="llm_calls")
    op.drop_index("ix_llm_calls_user_ts", table_name="llm_calls")
