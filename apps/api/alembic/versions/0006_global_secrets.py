"""Allow a secret that belongs to no project.

Migration 0002 made `secrets.project_id` NOT NULL, which was right when every secret
belonged to a project's data connection. Phase 3a adds GLOBAL LLM connections — one
org-wide model endpoint shared by every project, which is the main reason to have a
global connection at all — and its API key belongs to the platform, not to any project.

With the NOT NULL in place a global connection simply could not hold a credential, so
the feature was unusable rather than merely awkward.

Revision ID: 0006
Revises: 0005
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("secrets", "project_id", existing_type=sa.UUID(), nullable=True)


def downgrade() -> None:
    # Platform-level secrets have no project to fall back to, so they are removed rather
    # than silently reattached to an arbitrary one.
    op.execute("DELETE FROM secrets WHERE project_id IS NULL")
    op.alter_column("secrets", "project_id", existing_type=sa.UUID(), nullable=False)
