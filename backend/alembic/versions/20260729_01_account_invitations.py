"""add activation lifecycle and invitation tokens

Revision ID: 20260729_01
Revises:
Create Date: 2026-07-29
"""
from alembic import op
import sqlalchemy as sa

revision = "20260729_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(sa.Column(
            "activation_status", sa.String(), nullable=False, server_default="active"
        ))
    with op.batch_alter_table("users") as batch_op:
        batch_op.alter_column(
            "activation_status", existing_type=sa.String(),
            existing_nullable=False, server_default=None,
        )
    op.create_table(
        "invitation_tokens",
        sa.Column("invitation_token_id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.user_id"), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.user_id"), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("purpose", sa.String(), nullable=False, server_default="account_activation"),
        sa.Column("delivery_status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("consumed_at", sa.DateTime(), nullable=True),
        sa.Column("invalidated_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("token_hash", name="uq_invitation_tokens_token_hash"),
    )
    op.create_index("ix_invitation_tokens_user_id", "invitation_tokens", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_invitation_tokens_user_id", table_name="invitation_tokens")
    op.drop_table("invitation_tokens")
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("activation_status")
