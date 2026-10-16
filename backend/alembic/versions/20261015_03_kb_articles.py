"""add kb_articles table -- the narrative-content half of the clean KB

Phase 5 of the clean-schema project: every KB article gets one row here,
holding its verified narrative content (résumé, procedure, definitions --
whatever isn't a decision table). For articles backed by one or more
decision_tables (joined via kb_article_tables on kb_code), this is a short
intro; for the handful of purely narrative articles (no real Excel table
behind them at all), this holds the full verified content.

This table is purely additive and not yet read by the live chat pipeline --
the running chatbot still serves from the existing chunks.json/Milvus RAG
path. Building the complete new KB (decision tables + this) before any
cutover, per explicit instruction.

Revision ID: 20261015_03
Revises: 20261015_02
Create Date: 2026-10-15
"""

from alembic import op
import sqlalchemy as sa

revision = "20261015_03"
down_revision = "20261015_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "kb_articles",
        sa.Column("kb_article_id", sa.Integer(), primary_key=True),
        sa.Column("kb_code", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("perimeter", sa.String(), nullable=True),
        sa.Column("narrative_content", sa.Text(), nullable=True),
        sa.Column("content_scope", sa.String(), nullable=False),  # full | intro
        sa.Column("source_notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("kb_code", name="uq_kb_articles_kb_code"),
    )


def downgrade() -> None:
    op.drop_table("kb_articles")
