"""add user_flagged signal to knowledge_gaps

Revision ID: 20261002_01
Revises: 20260928_01
Create Date: 2026-10-02
"""

from alembic import op
import sqlalchemy as sa

revision = "20261002_01"
down_revision = "20260928_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "knowledge_gaps",
        sa.Column(
            "user_flagged", sa.Boolean(),
            nullable=False, server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("knowledge_gaps", "user_flagged")
