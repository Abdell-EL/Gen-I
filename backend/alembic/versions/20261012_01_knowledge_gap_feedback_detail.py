"""add feedback rating/reason/comment detail to knowledge_gaps

Revision ID: 20261012_01
Revises: 20261002_01
Create Date: 2026-10-12
"""

from alembic import op
import sqlalchemy as sa

revision = "20261012_01"
down_revision = "20261002_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("knowledge_gaps", sa.Column("user_feedback_rating", sa.String(), nullable=True))
    op.add_column("knowledge_gaps", sa.Column("user_feedback_reason", sa.String(), nullable=True))
    op.add_column("knowledge_gaps", sa.Column("user_feedback_comment", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("knowledge_gaps", "user_feedback_comment")
    op.drop_column("knowledge_gaps", "user_feedback_reason")
    op.drop_column("knowledge_gaps", "user_feedback_rating")
