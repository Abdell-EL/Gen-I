"""add knowledge_gaps table for unanswered-question tracking

Revision ID: 20260928_01
Revises: 20260730_01
Create Date: 2026-09-28
"""

from alembic import op
import sqlalchemy as sa

revision = "20260928_01"
down_revision = "20260730_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "knowledge_gaps",
        sa.Column("gap_id", sa.Integer(), primary_key=True),
        sa.Column(
            "session_id", sa.Integer(),
            sa.ForeignKey("chat_sessions.session_id"), nullable=True,
        ),
        sa.Column(
            "retrieval_id", sa.Integer(),
            sa.ForeignKey("retrieval_requests.retrieval_id"), nullable=True,
        ),
        sa.Column(
            "assistant_message_id", sa.Integer(),
            sa.ForeignKey("chat_messages.message_id"), nullable=True,
        ),
        sa.Column(
            "user_id", sa.Integer(),
            sa.ForeignKey("users.user_id"), nullable=False,
        ),
        sa.Column("question_text", sa.Text(), nullable=False),
        sa.Column("answer_text", sa.Text(), nullable=False),
        sa.Column("confidence_label", sa.String(), nullable=True),
        sa.Column(
            "text_indicates_missing", sa.Boolean(),
            nullable=False, server_default=sa.false(),
        ),
        sa.Column(
            "low_confidence", sa.Boolean(),
            nullable=False, server_default=sa.false(),
        ),
        sa.Column(
            "status", sa.String(), nullable=False, server_default="open",
        ),
        sa.Column(
            "created_at", sa.DateTime(), nullable=False, server_default=sa.func.now(),
        ),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column(
            "resolved_by", sa.Integer(),
            sa.ForeignKey("users.user_id"), nullable=True,
        ),
        sa.Column("resolution_notes", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_knowledge_gaps_status", "knowledge_gaps", ["status"]
    )
    op.create_index(
        "ix_knowledge_gaps_created_at", "knowledge_gaps", ["created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_knowledge_gaps_created_at", table_name="knowledge_gaps")
    op.drop_index("ix_knowledge_gaps_status", table_name="knowledge_gaps")
    op.drop_table("knowledge_gaps")
