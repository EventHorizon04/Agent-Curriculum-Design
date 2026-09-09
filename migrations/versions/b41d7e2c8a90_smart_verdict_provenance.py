"""smart verdict provenance and diagnosis

Revision ID: b41d7e2c8a90
Revises: a3f8d61e04c7
Create Date: 2026-09-09 10:00:00.000000

Two columns, both with server defaults so existing rows read back through
PLO.model_validate without a coercion layer.

SMARTCheck.findings — the richest part of a verdict — needs no column: it rides
inside the existing smart_check JSONB, and a row written before it deserialises
on the model's default_factory.

"legacy" is the deliberate default for smart_validated_by rather than "agent":
a row written before any agent existed was not validated by one, and claiming
otherwise would have the UI attribute a diagnosis to something that never ran.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b41d7e2c8a90"
down_revision: Union[str, None] = "a3f8d61e04c7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "plos",
        sa.Column(
            "smart_validated_by",
            sa.String(20),
            nullable=False,
            server_default="legacy",
        ),
    )
    op.add_column("plos", sa.Column("smart_diagnosis_th", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("plos", "smart_diagnosis_th")
    op.drop_column("plos", "smart_validated_by")
