"""add decision_tables / decision_table_rows / kb_article_tables

Phase 2 of the clean-schema project: generic storage for the ~20 lookup-style
KB sources (formula-driven VLOOKUP tables and tabular screenshots), read
straight from the real Excel workbook instead of the DOCX intermediate.

Revision ID: 20261015_02
Revises: 20261015_01
Create Date: 2026-10-15
"""

from alembic import op
import sqlalchemy as sa

revision = "20261015_02"
down_revision = "20261015_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "decision_tables",
        sa.Column("table_id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("source_sheet", sa.String(), nullable=False),
        sa.Column("source_type", sa.String(), nullable=False),  # formula | flat_table | screenshot
        sa.Column("key_schema", sa.JSON(), nullable=True),
        sa.Column("value_schema", sa.JSON(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("row_count_expected", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("name", name="uq_decision_tables_name"),
    )

    op.create_table(
        "decision_table_rows",
        sa.Column("row_id", sa.Integer(), primary_key=True),
        sa.Column(
            "table_id", sa.Integer(),
            sa.ForeignKey("decision_tables.table_id"), nullable=False,
        ),
        sa.Column("key_columns", sa.JSON(), nullable=False),
        sa.Column("value_columns", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_decision_table_rows_table_id", "decision_table_rows", ["table_id"]
    )

    op.create_table(
        "kb_article_tables",
        sa.Column("kb_article_table_id", sa.Integer(), primary_key=True),
        sa.Column("kb_code", sa.String(), nullable=False),
        sa.Column(
            "table_id", sa.Integer(),
            sa.ForeignKey("decision_tables.table_id"), nullable=False,
        ),
        sa.UniqueConstraint("kb_code", "table_id", name="uq_kb_article_tables_kb_code_table_id"),
    )
    op.create_index(
        "ix_kb_article_tables_kb_code", "kb_article_tables", ["kb_code"]
    )


def downgrade() -> None:
    op.drop_table("kb_article_tables")
    op.drop_table("decision_table_rows")
    op.drop_table("decision_tables")
