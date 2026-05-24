"""add_oneway_to_road_segments

Revision ID: 4e915d42a9b2
Revises: e74fba094014
Create Date: 2026-05-19 14:59:01.781050

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "4e915d42a9b2"
down_revision: Union[str, None] = "e74fba094014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "road_segments",
        sa.Column("oneway", sa.Boolean(), server_default="false", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("road_segments", "oneway")
