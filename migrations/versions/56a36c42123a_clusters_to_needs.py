"""clusters table becomes needs

Revision ID: 56a36c42123a
Revises: 311b23e80959
Create Date: 2026-07-26 00:00:01.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '56a36c42123a'
down_revision: Union[str, None] = '311b23e80959'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Cluster rows cannot become Need rows: a Need needs a statement sentence and
    # a single KSEC tag that no cluster row carries. Programmes past Stage 2
    # re-run skill extraction, as recorded in the design spec.
    op.execute("DELETE FROM clusters")
    op.rename_table("clusters", "needs")
    op.alter_column("needs", "cluster_id", new_column_name="need_id")
    for col in (
        "canonical_name_th",
        "canonical_name_en",
        "description_th",
        "skill_type",
        "is_subject_specific",
        "psychomotor_level",
        "krathwohl_level",
        "is_common_need",
    ):
        op.drop_column("needs", col)
    # `clusters` never had a ksec_category column — it is added here, not altered.
    op.add_column("needs", sa.Column("ksec_category", sa.String(2), nullable=False,
                                     server_default="SS"))
    op.add_column("needs", sa.Column("statement_th", sa.Text(), nullable=False,
                                     server_default=""))
    op.add_column("needs", sa.Column("statement_en", sa.Text(), nullable=True))
    op.add_column("needs", sa.Column("freq", sa.Integer(), nullable=False, server_default="1"))
    # bloom_level existed and was nullable (cognitive clusters only); Needs always
    # carry one because every skill is Bloom-tagged.
    op.alter_column("needs", "bloom_level", existing_type=sa.String(20), nullable=False,
                    server_default="apply")


def downgrade() -> None:
    op.execute("DELETE FROM needs")
    op.alter_column("needs", "bloom_level", existing_type=sa.String(20), nullable=True,
                    server_default=None)
    op.drop_column("needs", "freq")
    op.drop_column("needs", "statement_en")
    op.drop_column("needs", "statement_th")
    op.drop_column("needs", "ksec_category")
    op.add_column("needs", sa.Column("is_common_need", sa.Boolean(), nullable=False,
                                     server_default=sa.false()))
    op.add_column("needs", sa.Column("krathwohl_level", sa.String(20), nullable=True))
    op.add_column("needs", sa.Column("psychomotor_level", sa.String(20), nullable=True))
    op.add_column("needs", sa.Column("is_subject_specific", sa.Boolean(), nullable=False,
                                     server_default=sa.true()))
    op.add_column("needs", sa.Column("skill_type", sa.String(20), nullable=False,
                                     server_default="knowledge"))
    op.add_column("needs", sa.Column("description_th", sa.Text(), nullable=False,
                                     server_default=""))
    op.add_column("needs", sa.Column("canonical_name_en", sa.Text(), nullable=True))
    op.add_column("needs", sa.Column("canonical_name_th", sa.Text(), nullable=False,
                                     server_default=""))
    op.alter_column("needs", "need_id", new_column_name="cluster_id")
    op.rename_table("needs", "clusters")
