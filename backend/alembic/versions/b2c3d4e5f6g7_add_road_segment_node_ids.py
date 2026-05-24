"""add road segment node ids

Revision ID: b2c3d4e5f6g7
Revises: a1b2c3d4e5f6
Create Date: 2026-05-17 17:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'b2c3d4e5f6g7'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('road_segments', sa.Column('start_node_id', sa.String(30), nullable=True))
    op.add_column('road_segments', sa.Column('end_node_id', sa.String(30), nullable=True))
    op.drop_constraint('road_segments_osm_way_id_key', 'road_segments', type_='unique')
    op.create_index('ix_road_segments_start_node', 'road_segments', ['start_node_id'])
    op.create_index('ix_road_segments_end_node', 'road_segments', ['end_node_id'])
    op.create_index(
        'ix_road_segments_geometry',
        'road_segments',
        ['geometry'],
        postgresql_using='gist',
    )


def downgrade() -> None:
    op.drop_index('ix_road_segments_geometry', 'road_segments')
    op.drop_index('ix_road_segments_end_node', 'road_segments')
    op.drop_index('ix_road_segments_start_node', 'road_segments')
    op.create_unique_constraint('road_segments_osm_way_id_key', 'road_segments', ['osm_way_id'])
    op.drop_column('road_segments', 'end_node_id')
    op.drop_column('road_segments', 'start_node_id')
