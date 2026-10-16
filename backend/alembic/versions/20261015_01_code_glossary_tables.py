"""add code glossary tables (closure codes, network segments, zones, regions, activite codes)

Revision ID: 20261015_01
Revises: 20261012_01
Create Date: 2026-10-15
"""

from alembic import op
import sqlalchemy as sa

revision = "20261015_01"
down_revision = "20261012_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "closure_codes",
        sa.Column("closure_code_id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("label", sa.String(), nullable=True),
        sa.Column("meaning", sa.Text(), nullable=True),
        sa.Column("family", sa.String(), nullable=True),
        sa.Column(
            "confidence", sa.String(), nullable=False,
            server_default="context_only",
        ),
        sa.Column("source_notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("code", name="uq_closure_codes_code"),
    )

    op.create_table(
        "network_segments",
        sa.Column("network_segment_id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("label", sa.String(), nullable=True),
        sa.Column("family", sa.String(), nullable=True),
        sa.Column(
            "confidence", sa.String(), nullable=False,
            server_default="context_only",
        ),
        sa.Column("source_notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("code", name="uq_network_segments_code"),
    )

    op.create_table(
        "zones",
        sa.Column("zone_id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("label", sa.String(), nullable=True),
        sa.Column("perimeter", sa.String(), nullable=True),
        sa.Column(
            "confidence", sa.String(), nullable=False,
            server_default="context_only",
        ),
        sa.Column("source_notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("code", name="uq_zones_code"),
    )

    op.create_table(
        "regions",
        sa.Column("region_id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("label", sa.String(), nullable=True),
        sa.Column(
            "confidence", sa.String(), nullable=False,
            server_default="context_only",
        ),
        sa.Column("source_notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("code", name="uq_regions_code"),
    )

    # code alone is NOT unique here: e.g. "IDV" exists as both a Cuivre activité
    # (GEM-CUIVRE-010) and an FTTH activité (Expertise & Fiabilisation GEM matrix),
    # with different eligibility rules in each. perimeter is part of the identity.
    op.create_table(
        "activite_codes",
        sa.Column("activite_code_id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("label", sa.String(), nullable=True),
        sa.Column("perimeter", sa.String(), nullable=False),
        sa.Column("family", sa.String(), nullable=True),
        sa.Column(
            "confidence", sa.String(), nullable=False,
            server_default="context_only",
        ),
        sa.Column("source_notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("code", "perimeter", name="uq_activite_codes_code_perimeter"),
    )


def downgrade() -> None:
    op.drop_table("activite_codes")
    op.drop_table("regions")
    op.drop_table("zones")
    op.drop_table("network_segments")
    op.drop_table("closure_codes")
