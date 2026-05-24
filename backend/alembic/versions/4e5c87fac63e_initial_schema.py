"""initial_schema

Revision ID: 4e5c87fac63e
Revises:
Create Date: 2026-05-13 18:54:51.278426

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import geoalchemy2

revision: str = '4e5c87fac63e'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('road_segments',
        sa.Column('osm_way_id', sa.BigInteger(), nullable=True),
        sa.Column('geometry', geoalchemy2.types.Geometry(geometry_type='LINESTRING', srid=4326, from_text='ST_GeomFromEWKT', name='geometry', nullable=False), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=True),
        sa.Column('road_type', sa.String(length=50), nullable=True),
        sa.Column('speed_limit', sa.Integer(), nullable=True),
        sa.Column('length_m', sa.REAL(), nullable=True),
        sa.Column('lanes', sa.SmallInteger(), nullable=True),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('osm_way_id'),
    )

    op.create_table('users',
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('password_hash', sa.String(), nullable=False),
        sa.Column('role', sa.Enum('dispatcher', 'driver', 'admin', name='user_role'), nullable=False),
        sa.Column('full_name', sa.String(length=255), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('email'),
    )

    op.create_table('incidents',
        sa.Column('reported_by', sa.Uuid(), nullable=False),
        sa.Column('type', sa.Enum('accident', 'congestion', 'roadwork', 'weather', 'other', name='incident_type'), nullable=False),
        sa.Column('location', geoalchemy2.types.Geometry(geometry_type='POINT', srid=4326, from_text='ST_GeomFromEWKT', name='geometry', nullable=False), nullable=False),
        sa.Column('severity', sa.Enum('low', 'medium', 'high', name='severity_level'), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('is_simulated', sa.Boolean(), nullable=False),
        sa.Column('reported_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(['reported_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table('traffic_predictions',
        sa.Column('segment_id', sa.Uuid(), nullable=False),
        sa.Column('predicted_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('prediction_for', sa.DateTime(timezone=True), nullable=False),
        sa.Column('congestion_level', sa.Float(), nullable=True),
        sa.Column('avg_speed_kmh', sa.Float(), nullable=True),
        sa.Column('confidence', sa.Float(), nullable=True),
        sa.Column('model_version', sa.String(length=50), nullable=True),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(['segment_id'], ['road_segments.id']),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table('vehicles',
        sa.Column('driver_id', sa.Uuid(), nullable=False),
        sa.Column('license_plate', sa.String(length=20), nullable=False),
        sa.Column('vehicle_type', sa.String(length=50), nullable=True),
        sa.Column('status', sa.Enum('active', 'idle', 'offline', name='vehicle_status'), nullable=False),
        sa.Column('current_position', geoalchemy2.types.Geometry(geometry_type='POINT', srid=4326, from_text='ST_GeomFromEWKT', name='geometry'), nullable=True),
        sa.Column('last_seen', sa.DateTime(timezone=True), nullable=True),
        sa.Column('is_simulated', sa.Boolean(), nullable=False),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(['driver_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('license_plate'),
    )

    op.create_table('routes',
        sa.Column('vehicle_id', sa.Uuid(), nullable=False),
        sa.Column('status', sa.Enum('active', 'completed', 'cancelled', name='route_status'), nullable=False),
        sa.Column('origin', geoalchemy2.types.Geometry(geometry_type='POINT', srid=4326, from_text='ST_GeomFromEWKT', name='geometry', nullable=False), nullable=False),
        sa.Column('destination', geoalchemy2.types.Geometry(geometry_type='POINT', srid=4326, from_text='ST_GeomFromEWKT', name='geometry', nullable=False), nullable=False),
        sa.Column('waypoints', geoalchemy2.types.Geometry(geometry_type='LINESTRING', srid=4326, from_text='ST_GeomFromEWKT', name='geometry'), nullable=True),
        sa.Column('distance_km', sa.Float(), nullable=True),
        sa.Column('eta_minutes', sa.Integer(), nullable=True),
        sa.Column('recalculation_count', sa.Integer(), nullable=False),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['vehicle_id'], ['vehicles.id']),
        sa.PrimaryKeyConstraint('id'),
    )

    # Partitioned telemetry table — Alembic doesn't support PARTITION BY natively,
    # so we use raw SQL.
    op.execute("""
        CREATE TABLE telemetry (
            time        TIMESTAMPTZ NOT NULL,
            vehicle_id  UUID NOT NULL REFERENCES vehicles(id),
            latitude    DOUBLE PRECISION NOT NULL,
            longitude   DOUBLE PRECISION NOT NULL,
            speed_kmh   REAL,
            heading     REAL,
            road_segment_id UUID REFERENCES road_segments(id),
            PRIMARY KEY (time, vehicle_id)
        ) PARTITION BY RANGE (time)
    """)

    # Create initial weekly partitions (4 weeks back + 8 weeks forward)
    op.execute("""
        DO $$
        DECLARE
            start_date DATE := date_trunc('week', CURRENT_DATE) - INTERVAL '4 weeks';
            end_date   DATE;
            i          INT;
        BEGIN
            FOR i IN 0..11 LOOP
                end_date := start_date + INTERVAL '1 week';
                EXECUTE format(
                    'CREATE TABLE telemetry_%s PARTITION OF telemetry FOR VALUES FROM (%L) TO (%L)',
                    to_char(start_date, 'IYYY_IW'),
                    start_date,
                    end_date
                );
                start_date := end_date;
            END LOOP;
        END $$;
    """)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP TABLE IF EXISTS telemetry CASCADE")
    op.drop_table('routes')
    op.drop_table('vehicles')
    op.drop_table('traffic_predictions')
    op.drop_table('incidents')
    op.drop_table('users')
    op.drop_table('road_segments')
    sa.Enum(name='user_role').drop(op.get_bind())
    sa.Enum(name='incident_type').drop(op.get_bind())
    sa.Enum(name='severity_level').drop(op.get_bind())
    sa.Enum(name='vehicle_status').drop(op.get_bind())
    sa.Enum(name='route_status').drop(op.get_bind())
