"""add decision_table_links -- table-to-table chaining, since the tables are
NOT independent (several tables' own output text says "see X", confirmed
by reading every decision_table_row for "voir" cross-references)

Revision ID: 20261015_04
Revises: 20261015_03
Create Date: 2026-10-15
"""

from alembic import op
import sqlalchemy as sa

revision = "20261015_04"
down_revision = "20261015_03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "decision_table_links",
        sa.Column("link_id", sa.Integer(), primary_key=True),
        sa.Column(
            "source_table_id", sa.Integer(),
            sa.ForeignKey("decision_tables.table_id"), nullable=False,
        ),
        sa.Column(
            "target_table_id", sa.Integer(),
            sa.ForeignKey("decision_tables.table_id"), nullable=False,
        ),
        sa.Column("trigger_description", sa.Text(), nullable=False),
        sa.Column("source_text_pattern", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_decision_table_links_source", "decision_table_links", ["source_table_id"]
    )


def downgrade() -> None:
    op.drop_table("decision_table_links")
