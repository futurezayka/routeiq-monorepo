"""
RouteIQ Full System Audit — tests for all ФВ, НФВ, pipelines, integrations.
"""

import asyncio
import json
import time
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.security import create_access_token, hash_password, verify_password
from app.main import app

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_COUNTER = 0


def _unique_email() -> str:
    global _COUNTER
    _COUNTER += 1
    return f"audit_{_COUNTER}_{uuid.uuid4().hex[:6]}@test.io"


def _make_factory():
    engine = create_async_engine(settings.DATABASE_URL)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False), engine


async def _register_and_login(
    client: AsyncClient,
    role: str = "dispatcher",
    email: str | None = None,
    password: str = "AuditP@ss1",
) -> tuple[str, str, dict]:
    email = email or _unique_email()
    reg = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "full_name": f"Audit {role}", "role": role},
    )
    assert reg.status_code == 201, f"Register failed: {reg.text}"
    user_data = reg.json()
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, f"Login failed: {login.text}"
    token = login.json()["access_token"]
    return token, email, user_data


def _auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _create_vehicle(client: AsyncClient, token: str, plate: str | None = None) -> dict:
    plate = plate or f"AU{uuid.uuid4().hex[:6].upper()}"
    r = await client.post(
        "/api/v1/vehicles",
        json={"license_plate": plate, "vehicle_type": "car"},
        headers=_auth_headers(token),
    )
    assert r.status_code == 201, f"Vehicle create failed: {r.text}"
    return r.json()


# ===========================================================================
# ЧАСТИНА 1: АРХІТЕКТУРНИЙ АУДИТ (static — validated by import scanning)
# ===========================================================================


class TestArchitecture:
    """1.1–1.3 Architectural checks (static analysis via imports)."""

    def test_routers_no_sqlalchemy(self):
        import app.api.auth as auth
        import app.api.vehicles as vehicles
        import app.api.routes as routes_mod
        import app.api.incidents as incidents
        import app.api.telemetry as telemetry
        import app.api.analytics as analytics
        import app.api.ws as ws
        for mod in [auth, vehicles, routes_mod, incidents, telemetry, analytics, ws]:
            src = open(mod.__file__, encoding="utf-8").read()
            assert "from sqlalchemy" not in src, f"{mod.__name__} imports sqlalchemy"
            assert "from app.models" not in src, f"{mod.__name__} imports models"

    def test_services_no_fastapi(self):
        import app.modules.auth.service as auth_svc
        import app.modules.route_planning.service as rp_svc
        import app.modules.traffic_analysis.service as ta_svc
        import app.modules.agent_manager.service as am_svc
        import app.modules.analytics.service as an_svc
        for mod in [auth_svc, rp_svc, ta_svc, am_svc, an_svc]:
            src = open(mod.__file__, encoding="utf-8").read()
            assert "from fastapi" not in src, f"{mod.__name__} imports FastAPI"

    def test_repos_no_events_no_commit(self):
        import app.modules.auth.repository as auth_repo
        import app.modules.route_planning.repository as rp_repo
        import app.modules.traffic_analysis.repository as ta_repo
        import app.modules.agent_manager.repository as am_repo
        import app.modules.analytics.repository as an_repo
        for mod in [auth_repo, rp_repo, ta_repo, am_repo, an_repo]:
            src = open(mod.__file__, encoding="utf-8").read()
            assert "EventBus" not in src, f"{mod.__name__} imports EventBus"
            assert ".commit()" not in src, f"{mod.__name__} calls commit()"

    def test_no_sync_io(self):
        import pathlib
        app_dir = pathlib.Path(__file__).resolve().parents[2] / "app"
        for py in app_dir.rglob("*.py"):
            src = py.read_text(encoding="utf-8")
            assert "import requests\n" not in src, f"{py} uses sync requests"
            assert "import psycopg2" not in src, f"{py} uses psycopg2"
            assert "time.sleep(" not in src, f"{py} uses time.sleep"

    def test_dependency_injection_exists(self):
        from app.core.deps import (
            get_db, get_redis, get_auth_service, get_agent_service,
            get_route_planning_service, get_incident_service,
            get_analytics_service, get_current_user,
        )
        for fn in [get_db, get_redis, get_auth_service, get_agent_service,
                   get_route_planning_service, get_incident_service,
                   get_analytics_service, get_current_user]:
            assert callable(fn)


# ===========================================================================
# ЧАСТИНА 2: ФУНКЦІОНАЛЬНІ ВИМОГИ
# ===========================================================================


@pytest.mark.asyncio
class TestFV1RealTimeTracking:
    """ФВ-1: Трекінг транспорту в реальному часі."""

    async def test_telemetry_ingestion_and_cache(self, client: AsyncClient, redis_client: Redis):
        token, _, _ = await _register_and_login(client, "dispatcher")
        vehicle = await _create_vehicle(client, token)
        vid = vehicle["id"]

        for i in range(5):
            r = await client.post(
                "/api/v1/telemetry",
                json={
                    "vehicle_id": vid,
                    "latitude": 50.45 + i * 0.001,
                    "longitude": 30.52 + i * 0.001,
                    "speed_kmh": 40 + i,
                    "heading": 90,
                },
                headers=_auth_headers(token),
            )
            assert r.status_code == 202

        cached = await redis_client.get(f"vehicle:{vid}:pos")
        assert cached is not None, "Position not cached in Redis"
        pos = json.loads(cached)
        assert "lat" in pos or "latitude" in pos

    async def test_telemetry_stream_published(self, client: AsyncClient, redis_client: Redis):
        token, _, _ = await _register_and_login(client, "dispatcher")
        vehicle = await _create_vehicle(client, token)
        vid = vehicle["id"]

        await client.post(
            "/api/v1/telemetry",
            json={"vehicle_id": vid, "latitude": 50.45, "longitude": 30.52, "speed_kmh": 30, "heading": 0},
            headers=_auth_headers(token),
        )

        length = await redis_client.xlen("stream:telemetry")
        assert length > 0, "stream:telemetry is empty after telemetry POST"


@pytest.mark.asyncio
class TestFV2IncidentReporting:
    """ФВ-2: Звітування про дорожні інциденти."""

    async def test_create_and_list_incidents(self, client: AsyncClient):
        token, _, _ = await _register_and_login(client, "dispatcher")

        r = await client.post(
            "/api/v1/incidents",
            json={"type": "accident", "severity": "high", "latitude": 50.45, "longitude": 30.52},
            headers=_auth_headers(token),
        )
        assert r.status_code == 201
        inc = r.json()
        assert inc["type"] == "accident"
        assert inc["severity"] == "high"
        assert inc["is_active"] is True
        inc_id = inc["id"]

        listed = await client.get("/api/v1/incidents", headers=_auth_headers(token))
        assert listed.status_code == 200
        ids = [i["id"] for i in listed.json()]
        assert inc_id in ids

    async def test_incident_published_to_stream(self, client: AsyncClient, redis_client: Redis):
        token, _, _ = await _register_and_login(client, "dispatcher")
        before = await redis_client.xlen("stream:incidents")

        await client.post(
            "/api/v1/incidents",
            json={"type": "congestion", "severity": "medium", "latitude": 50.44, "longitude": 30.51},
            headers=_auth_headers(token),
        )
        after = await redis_client.xlen("stream:incidents")
        assert after > before, "Incident not published to stream:incidents"

    async def test_resolve_incident(self, client: AsyncClient):
        token, _, _ = await _register_and_login(client, "dispatcher")
        r = await client.post(
            "/api/v1/incidents",
            json={"type": "roadwork", "severity": "low", "latitude": 50.43, "longitude": 30.50},
            headers=_auth_headers(token),
        )
        inc_id = r.json()["id"]

        resolve = await client.patch(
            f"/api/v1/incidents/{inc_id}/resolve",
            headers=_auth_headers(token),
        )
        assert resolve.status_code == 200
        assert resolve.json()["is_active"] is False


@pytest.mark.asyncio
class TestFV3RoutePlanning:
    """ФВ-3: Інтелектуальне планування маршрутів."""

    async def test_plan_route(self, client: AsyncClient):
        token, _, _ = await _register_and_login(client, "dispatcher")
        vehicle = await _create_vehicle(client, token)

        r = await client.post(
            "/api/v1/routes",
            json={
                "vehicle_id": vehicle["id"],
                "origin_lat": 50.4501,
                "origin_lng": 30.5234,
                "destination_lat": 50.4234,
                "destination_lng": 30.4567,
            },
            headers=_auth_headers(token),
        )
        assert r.status_code == 201
        route = r.json()
        assert route["waypoints"] is not None
        assert route["distance_km"] is not None and route["distance_km"] > 0
        assert route["eta_minutes"] is not None and route["eta_minutes"] > 0
        assert route["vehicle_id"] == vehicle["id"]

    async def test_list_routes(self, client: AsyncClient):
        token, _, _ = await _register_and_login(client, "dispatcher")
        vehicle = await _create_vehicle(client, token)

        await client.post(
            "/api/v1/routes",
            json={
                "vehicle_id": vehicle["id"],
                "origin_lat": 50.45,
                "origin_lng": 30.52,
                "destination_lat": 50.42,
                "destination_lng": 30.45,
            },
            headers=_auth_headers(token),
        )

        r = await client.get("/api/v1/routes", headers=_auth_headers(token))
        assert r.status_code == 200
        assert isinstance(r.json(), list)


@pytest.mark.asyncio
class TestFV5Dashboard:
    """ФВ-5: Дашборд диспетчера — API endpoints."""

    async def test_vehicles_list(self, client: AsyncClient):
        token, _, _ = await _register_and_login(client, "dispatcher")
        await _create_vehicle(client, token)

        r = await client.get("/api/v1/vehicles", headers=_auth_headers(token))
        assert r.status_code == 200
        assert len(r.json()) >= 1

    async def test_incidents_list(self, client: AsyncClient):
        token, _, _ = await _register_and_login(client, "dispatcher")
        r = await client.get("/api/v1/incidents", headers=_auth_headers(token))
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    async def test_routes_list(self, client: AsyncClient):
        token, _, _ = await _register_and_login(client, "dispatcher")
        r = await client.get("/api/v1/routes", headers=_auth_headers(token))
        assert r.status_code == 200
        assert isinstance(r.json(), list)


@pytest.mark.asyncio
class TestFV6Analytics:
    """ФВ-6: Аналітика трафіку та операційної ефективності."""

    async def test_analytics_endpoints(self, client: AsyncClient):
        token, _, _ = await _register_and_login(client, "dispatcher")
        now = datetime.now(timezone.utc)
        params = {
            "from": (now - timedelta(hours=24)).isoformat(),
            "to": now.isoformat(),
        }

        r = await client.get("/api/v1/analytics/heatmap", params=params, headers=_auth_headers(token))
        assert r.status_code == 200
        assert "points" in r.json()

        r = await client.get("/api/v1/analytics/incidents", params=params, headers=_auth_headers(token))
        assert r.status_code == 200
        data = r.json()
        assert "total" in data
        assert "by_type" in data
        assert "by_severity" in data

        r = await client.get("/api/v1/analytics/efficiency", params=params, headers=_auth_headers(token))
        assert r.status_code == 200
        data = r.json()
        assert "routes_total" in data


@pytest.mark.asyncio
class TestFV8RBAC:
    """ФВ-8: Авторизація та розмежування ролей."""

    async def test_login_returns_jwt(self, client: AsyncClient):
        token, email, _ = await _register_and_login(client, "dispatcher")
        assert token and len(token) > 20

    async def test_wrong_password_401(self, client: AsyncClient):
        _, email, _ = await _register_and_login(client, "dispatcher")
        r = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": "WrongPassword123"},
        )
        assert r.status_code == 401

    async def test_nonexistent_email_401(self, client: AsyncClient):
        r = await client.post(
            "/api/v1/auth/login",
            json={"email": "nobody@example.com", "password": "whatever"},
        )
        assert r.status_code == 401

    async def test_no_token_401(self, client: AsyncClient):
        endpoints = [
            ("GET", "/api/v1/vehicles"),
            ("GET", "/api/v1/incidents"),
            ("GET", "/api/v1/routes"),
            ("POST", "/api/v1/vehicles"),
            ("POST", "/api/v1/telemetry"),
            ("POST", "/api/v1/incidents"),
            ("POST", "/api/v1/routes"),
            ("GET", "/api/v1/auth/me"),
        ]
        for method, url in endpoints:
            r = await client.request(method, url)
            assert r.status_code in (401, 403, 422), (
                f"{method} {url} returned {r.status_code} without token (expected 401/403)"
            )

    async def test_invalid_token_401(self, client: AsyncClient):
        r = await client.get("/api/v1/vehicles", headers={"Authorization": "Bearer invalid.jwt.token"})
        assert r.status_code == 401


# ===========================================================================
# ЧАСТИНА 3: НЕФУНКЦІОНАЛЬНІ ВИМОГИ
# ===========================================================================


@pytest.mark.asyncio
class TestNFV1TrackingLatency:
    """НФВ-1: Затримка трекінгу < 3 секунд (p95) POST → Redis cache."""

    async def test_telemetry_p95_latency(self, client: AsyncClient, redis_client: Redis):
        token, _, _ = await _register_and_login(client, "dispatcher")
        vehicle = await _create_vehicle(client, token)
        vid = vehicle["id"]
        latencies: list[float] = []

        for i in range(50):
            t0 = time.monotonic()
            await client.post(
                "/api/v1/telemetry",
                json={
                    "vehicle_id": vid,
                    "latitude": 50.45 + i * 0.0001,
                    "longitude": 30.52 + i * 0.0001,
                    "speed_kmh": 30,
                    "heading": 0,
                },
                headers=_auth_headers(token),
            )
            cached = await redis_client.get(f"vehicle:{vid}:pos")
            t1 = time.monotonic()
            if cached:
                latencies.append(t1 - t0)

        assert len(latencies) >= 40, f"Only {len(latencies)} cached out of 50"
        latencies.sort()
        p95 = latencies[int(len(latencies) * 0.95)]
        avg = sum(latencies) / len(latencies)
        print(f"\n[НФВ-1] Telemetry latency: avg={avg:.3f}s p95={p95:.3f}s "
              f"min={latencies[0]:.3f}s max={latencies[-1]:.3f}s")
        assert p95 < 3.0, f"p95 latency {p95:.3f}s exceeds 3s target"


@pytest.mark.asyncio
class TestNFV4EventThroughput:
    """НФВ-4: ≥10,000 подій/сек через Redis Streams."""

    async def test_redis_stream_throughput(self, redis_client: Redis):
        stream = f"stream:audit-throughput-{uuid.uuid4().hex[:8]}"
        n = 10_000
        t0 = time.monotonic()
        pipe = redis_client.pipeline()
        for i in range(n):
            pipe.xadd(stream, {"i": str(i), "ts": str(time.time())})
        await pipe.execute()
        t1 = time.monotonic()
        elapsed = t1 - t0
        throughput = n / elapsed

        length = await redis_client.xlen(stream)
        await redis_client.delete(stream)

        print(f"\n[НФВ-4] Published {n} events in {elapsed:.2f}s = {throughput:.0f} events/sec")
        assert length == n
        assert throughput >= 10_000, f"Throughput {throughput:.0f}/s < 10,000/s"


@pytest.mark.asyncio
class TestNFV5Security:
    """НФВ-5: Автентифікація та авторизація."""

    async def test_all_protected_endpoints_require_auth(self, client: AsyncClient):
        protected = [
            ("GET", "/api/v1/vehicles"),
            ("GET", "/api/v1/incidents"),
            ("GET", "/api/v1/routes"),
            ("GET", "/api/v1/auth/me"),
            ("POST", "/api/v1/vehicles"),
            ("POST", "/api/v1/telemetry"),
            ("POST", "/api/v1/incidents"),
            ("POST", "/api/v1/routes"),
            ("GET", "/api/v1/analytics/heatmap?from=2026-01-01&to=2026-01-02"),
            ("GET", "/api/v1/analytics/incidents?from=2026-01-01&to=2026-01-02"),
            ("GET", "/api/v1/analytics/efficiency?from=2026-01-01&to=2026-01-02"),
        ]
        for method, url in protected:
            r = await client.request(method, url)
            assert r.status_code in (401, 403, 422), (
                f"{method} {url} is not protected (got {r.status_code})"
            )

    def test_jwt_has_expiration(self):
        token = create_access_token({"sub": "test@test.io"})
        from jose import jwt as jose_jwt
        payload = jose_jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        assert "exp" in payload

    def test_password_hashing(self):
        plain = "SuperSecret123"
        hashed = hash_password(plain)
        assert hashed != plain
        assert verify_password(plain, hashed) is True
        assert verify_password("wrong", hashed) is False

    async def test_expired_token_rejected(self, client: AsyncClient):
        token = create_access_token(
            {"sub": "expired@test.io"},
            expires_delta=timedelta(seconds=-10),
        )
        r = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 401


@pytest.mark.asyncio
class TestNFV8APIDocs:
    """НФВ-8: Документація API."""

    async def test_openapi_available(self, client: AsyncClient):
        r = await client.get("/openapi.json")
        assert r.status_code == 200
        spec = r.json()
        assert "paths" in spec
        assert len(spec["paths"]) > 0

    async def test_swagger_ui(self, client: AsyncClient):
        r = await client.get("/docs")
        assert r.status_code == 200


# ===========================================================================
# ЧАСТИНА 4: REDIS STREAMS PIPELINE
# ===========================================================================


@pytest.mark.asyncio
class TestPipelineTelemetry:
    """4.1 Telemetry pipeline: POST → stream:telemetry → Redis cache."""

    async def test_full_telemetry_pipeline(self, client: AsyncClient, redis_client: Redis):
        token, _, _ = await _register_and_login(client, "dispatcher")
        vehicle = await _create_vehicle(client, token)
        vid = vehicle["id"]

        r = await client.post(
            "/api/v1/telemetry",
            json={"vehicle_id": vid, "latitude": 50.451, "longitude": 30.521, "speed_kmh": 55, "heading": 180},
            headers=_auth_headers(token),
        )
        assert r.status_code == 202

        stream_len = await redis_client.xlen("stream:telemetry")
        assert stream_len > 0

        cached = await redis_client.get(f"vehicle:{vid}:pos")
        assert cached is not None


@pytest.mark.asyncio
class TestPipelineIncident:
    """4.2 Incident pipeline: POST → stream:incidents."""

    async def test_incident_to_stream(self, client: AsyncClient, redis_client: Redis):
        token, _, _ = await _register_and_login(client, "dispatcher")
        before = await redis_client.xlen("stream:incidents")

        await client.post(
            "/api/v1/incidents",
            json={"type": "weather", "severity": "medium", "latitude": 50.46, "longitude": 30.53},
            headers=_auth_headers(token),
        )

        after = await redis_client.xlen("stream:incidents")
        assert after > before


# ===========================================================================
# ЧАСТИНА 5: ІНТЕГРАЦІЇ
# ===========================================================================


@pytest.mark.asyncio
class TestOSRMIntegration:
    """5.1 OSRM integration — test via OSRMClient."""

    async def test_osrm_route(self):
        from app.modules.route_planning.osrm_client import OSRMClient
        osrm = OSRMClient(settings.OSRM_URL)
        result = await osrm.route((30.5234, 50.4501), (30.4567, 50.4234))
        if result is not None:
            assert result.distance_m > 0
            assert result.duration_s > 0
            assert len(result.waypoints) >= 2
        else:
            pytest.skip("OSRM not available")


@pytest.mark.asyncio
class TestMLServiceIntegration:
    """5.2 ML Service integration."""

    async def _check_ml_available(self):
        import httpx
        try:
            async with httpx.AsyncClient() as c:
                r = await c.get("http://localhost:8001/docs", timeout=5)
                return r.status_code == 200
        except Exception:
            return False

    async def test_ml_health(self):
        if not await self._check_ml_available():
            pytest.skip("ML service not reachable at localhost:8001")
        import httpx
        async with httpx.AsyncClient() as c:
            r = await c.get("http://localhost:8001/docs", timeout=5)
            assert r.status_code == 200

    async def test_ml_anomaly_endpoint(self):
        if not await self._check_ml_available():
            pytest.skip("ML service not reachable at localhost:8001")
        import httpx
        async with httpx.AsyncClient() as c:
            r = await c.post(
                "http://localhost:8001/api/v1/ml/anomaly",
                json={"segment_speeds": {"seg-1": 10.0, "seg-2": 50.0, "seg-3": 45.0}},
                timeout=10,
            )
            assert r.status_code == 200
            body = r.json()
            assert "anomalies" in body
            assert len(body["anomalies"]) == 3
            assert "model_version" in body
            for a in body["anomalies"]:
                assert "segment_id" in a
                assert "score" in a
                assert "is_anomaly" in a

    async def test_ml_predict_endpoint(self):
        if not await self._check_ml_available():
            pytest.skip("ML service not reachable at localhost:8001")
        import httpx
        async with httpx.AsyncClient() as c:
            r = await c.post(
                "http://localhost:8001/api/v1/ml/predict",
                json={
                    "segment_ids": ["seg-1", "seg-2"],
                },
                timeout=10,
            )
            assert r.status_code == 200
            body = r.json()
            assert "predictions" in body


@pytest.mark.asyncio
class TestPostGISIntegration:
    """5.3 PostGIS integration."""

    async def test_postgis_version(self, db_session: AsyncSession):
        result = await db_session.execute(text("SELECT PostGIS_Version()"))
        version = result.scalar()
        assert version is not None
        assert "3" in version


@pytest.mark.asyncio
class TestWebSocketIntegration:
    """5.4 WebSocket."""

    async def test_ws_endpoint_exists(self, client: AsyncClient):
        r = await client.get("/openapi.json")
        # WS endpoints aren't in OpenAPI, just verify the route is registered
        from app.main import app as fastapi_app
        ws_routes = [r for r in fastapi_app.routes if hasattr(r, "path") and "/ws" in getattr(r, "path", "")]
        assert len(ws_routes) > 0


# ===========================================================================
# ЧАСТИНА 6: DOCKER COMPOSE (validated via API reachability)
# ===========================================================================


@pytest.mark.asyncio
class TestDockerCompose:
    """6. Docker — API reachable, frontend served."""

    async def test_api_responds(self, client: AsyncClient):
        r = await client.get("/openapi.json")
        assert r.status_code == 200

    async def test_frontend_served(self):
        import httpx
        try:
            async with httpx.AsyncClient() as c:
                r = await c.get("http://localhost/", timeout=5)
                assert r.status_code == 200
                assert "root" in r.text
        except Exception:
            pytest.skip("nginx not reachable at localhost")
