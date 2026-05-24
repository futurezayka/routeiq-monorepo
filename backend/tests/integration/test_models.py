import uuid
from datetime import datetime, timezone

import pytest
from geoalchemy2.shape import from_shape, to_shape
from shapely.geometry import LineString, Point
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Incident,
    RoadSegment,
    Route,
    Telemetry,
    TrafficPrediction,
    User,
    Vehicle,
)


@pytest.fixture
def user_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def vehicle_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def segment_id() -> uuid.UUID:
    return uuid.uuid4()


async def test_create_user(db_session: AsyncSession) -> None:
    email = f"test_{uuid.uuid4().hex[:8]}@routeiq.io"
    user = User(
        email=email,
        password_hash="hashed_pw",
        role="dispatcher",
        full_name="Test User",
    )
    db_session.add(user)
    await db_session.flush()

    result = await db_session.execute(select(User).where(User.email == email))
    saved = result.scalar_one()
    assert saved.id is not None
    assert saved.email == email
    assert saved.role == "dispatcher"
    assert saved.full_name == "Test User"
    assert saved.is_active is True
    assert saved.created_at is not None


async def test_create_road_segment(db_session: AsyncSession, segment_id: uuid.UUID) -> None:
    segment = RoadSegment(
        id=segment_id,
        osm_way_id=123456789,
        geometry=from_shape(LineString([(30.5, 50.4), (30.6, 50.5)]), srid=4326),
        name="Khreshchatyk",
        road_type="primary",
        speed_limit=50,
        length_m=1200.5,
        lanes=4,
    )
    db_session.add(segment)
    await db_session.flush()

    result = await db_session.execute(select(RoadSegment).where(RoadSegment.id == segment_id))
    saved = result.scalar_one()
    assert saved.osm_way_id == 123456789
    assert saved.name == "Khreshchatyk"
    assert saved.speed_limit == 50
    assert saved.lanes == 4


async def test_create_vehicle(db_session: AsyncSession) -> None:
    user = User(
        email="driver@routeiq.io",
        password_hash="hashed_pw",
        role="driver",
        full_name="Driver One",
    )
    db_session.add(user)
    await db_session.flush()

    vehicle = Vehicle(
        driver_id=user.id,
        license_plate="AA1234BB",
        vehicle_type="van",
        status="active",
        current_position=from_shape(Point(30.5, 50.4), srid=4326),
    )
    db_session.add(vehicle)
    await db_session.flush()

    result = await db_session.execute(select(Vehicle).where(Vehicle.license_plate == "AA1234BB"))
    saved = result.scalar_one()
    assert saved.driver_id == user.id
    assert saved.status == "active"
    assert saved.vehicle_type == "van"
    assert saved.is_simulated is False


async def test_create_route(db_session: AsyncSession) -> None:
    user = User(
        email="driver2@routeiq.io",
        password_hash="hashed_pw",
        role="driver",
        full_name="Driver Two",
    )
    db_session.add(user)
    await db_session.flush()

    vehicle = Vehicle(
        driver_id=user.id,
        license_plate="CC5678DD",
        vehicle_type="truck",
    )
    db_session.add(vehicle)
    await db_session.flush()

    route = Route(
        vehicle_id=vehicle.id,
        origin=from_shape(Point(30.5, 50.4), srid=4326),
        destination=from_shape(Point(30.7, 50.5), srid=4326),
        waypoints=from_shape(LineString([(30.5, 50.4), (30.6, 50.45), (30.7, 50.5)]), srid=4326),
        distance_km=15.3,
        eta_minutes=25,
    )
    db_session.add(route)
    await db_session.flush()

    result = await db_session.execute(select(Route).where(Route.vehicle_id == vehicle.id))
    saved = result.scalar_one()
    assert saved.status == "active"
    assert saved.distance_km == pytest.approx(15.3)
    assert saved.eta_minutes == 25
    assert saved.recalculation_count == 0


async def test_create_incident(db_session: AsyncSession) -> None:
    user = User(
        email="dispatcher2@routeiq.io",
        password_hash="hashed_pw",
        role="dispatcher",
        full_name="Dispatcher Two",
    )
    db_session.add(user)
    await db_session.flush()

    incident = Incident(
        reported_by=user.id,
        type="accident",
        location=from_shape(Point(30.5, 50.4), srid=4326),
        severity="high",
    )
    db_session.add(incident)
    await db_session.flush()

    result = await db_session.execute(select(Incident).where(Incident.id == incident.id))
    saved = result.scalar_one()
    assert saved.type == "accident"
    assert saved.severity == "high"
    assert saved.is_active is True
    assert saved.is_simulated is False
    assert saved.resolved_at is None


async def test_create_telemetry(db_session: AsyncSession) -> None:
    user = User(
        email="driver3@routeiq.io",
        password_hash="hashed_pw",
        role="driver",
        full_name="Driver Three",
    )
    db_session.add(user)
    await db_session.flush()

    vehicle = Vehicle(
        driver_id=user.id,
        license_plate="EE9012FF",
        vehicle_type="sedan",
    )
    db_session.add(vehicle)
    await db_session.flush()

    now = datetime.now(timezone.utc)
    telemetry = Telemetry(
        time=now,
        vehicle_id=vehicle.id,
        latitude=50.4501,
        longitude=30.5234,
        speed_kmh=45.0,
        heading=180.0,
    )
    db_session.add(telemetry)
    await db_session.flush()

    result = await db_session.execute(
        select(Telemetry).where(
            Telemetry.vehicle_id == vehicle.id,
            Telemetry.time == now,
        )
    )
    saved = result.scalar_one()
    assert saved.latitude == pytest.approx(50.4501)
    assert saved.longitude == pytest.approx(30.5234)
    assert saved.speed_kmh == pytest.approx(45.0)
    assert saved.heading == pytest.approx(180.0)


async def test_create_traffic_prediction(db_session: AsyncSession, segment_id: uuid.UUID) -> None:
    segment = RoadSegment(
        id=segment_id,
        osm_way_id=987654321,
        geometry=from_shape(LineString([(30.5, 50.4), (30.6, 50.5)]), srid=4326),
        name="Peremohy Ave",
        road_type="secondary",
        speed_limit=60,
        length_m=2500.0,
        lanes=3,
    )
    db_session.add(segment)
    await db_session.flush()

    now = datetime.now(timezone.utc)
    prediction = TrafficPrediction(
        segment_id=segment_id,
        predicted_at=now,
        prediction_for=now,
        congestion_level=0.75,
        avg_speed_kmh=35.0,
        confidence=0.92,
        model_version="lstm-v1",
    )
    db_session.add(prediction)
    await db_session.flush()

    result = await db_session.execute(
        select(TrafficPrediction).where(TrafficPrediction.segment_id == segment_id)
    )
    saved = result.scalar_one()
    assert saved.congestion_level == pytest.approx(0.75)
    assert saved.avg_speed_kmh == pytest.approx(35.0)
    assert saved.confidence == pytest.approx(0.92)
    assert saved.model_version == "lstm-v1"
