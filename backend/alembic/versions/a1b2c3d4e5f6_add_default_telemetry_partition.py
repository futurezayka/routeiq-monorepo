"""add default telemetry partition

Revision ID: a1b2c3d4e5f6
Revises: eaa0d090ab78
Create Date: 2026-05-17 17:50:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'eaa0d090ab78'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("DROP TABLE IF EXISTS telemetry_test_default")
    op.execute(
        "CREATE TABLE IF NOT EXISTS telemetry_default "
        "PARTITION OF telemetry DEFAULT"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS telemetry_default")
