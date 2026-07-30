"""add password reset lifecycle and JWT versioning

Revision ID: 20260730_01
Revises: 20260729_01
Create Date: 2026-07-30
"""

from alembic import op
import sqlalchemy as sa

revision = "20260730_01"
down_revision = "20260729_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(sa.Column(
            "token_version", sa.Integer(), nullable=False, server_default="0"
        ))
    with op.batch_alter_table("users") as batch_op:
        batch_op.alter_column(
            "token_version", existing_type=sa.Integer(),
            existing_nullable=False, server_default=None,
        )
    op.create_table(
        "password_reset_tokens",
        sa.Column("password_reset_token_id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.user_id"), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("delivery_status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("consumed_at", sa.DateTime(), nullable=True),
        sa.Column("invalidated_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("token_hash", name="uq_password_reset_tokens_token_hash"),
    )
    op.create_index(
        "ix_password_reset_tokens_user_id", "password_reset_tokens", ["user_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_password_reset_tokens_user_id", table_name="password_reset_tokens")
    op.drop_table("password_reset_tokens")
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("token_version")
