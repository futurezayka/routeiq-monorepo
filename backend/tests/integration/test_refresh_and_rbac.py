import uuid

from httpx import AsyncClient


def _email(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}@routeiq.io"


async def _register(client: AsyncClient, role: str) -> tuple[str, str, str]:
    email = _email(f"rbac_{role}")
    password = "TestPass123"
    await client.post("/api/v1/auth/register", json={
        "email": email,
        "password": password,
        "full_name": f"{role.title()} User",
        "role": role,
    })
    login = await client.post("/api/v1/auth/login", json={
        "email": email,
        "password": password,
    })
    body = login.json()
    return body["access_token"], body["refresh_token"], email


async def test_refresh_valid_token_returns_new_token_pair(client: AsyncClient) -> None:
    _access, refresh, _ = await _register(client, "driver")

    resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
    assert resp.status_code == 200
    body = resp.json()
    assert "access_token" in body
    assert "refresh_token" in body
    assert body["token_type"] == "bearer"
    assert len(body["access_token"]) > 0


async def test_refresh_invalid_token_returns_401(client: AsyncClient) -> None:
    resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": "garbage.token.value"})
    assert resp.status_code == 401


async def test_driver_cannot_access_admin_endpoints(client: AsyncClient) -> None:
    access, _, _ = await _register(client, "driver")

    resp = await client.get(
        "/api/v1/admin/users",
        headers={"Authorization": f"Bearer {access}"},
    )
    assert resp.status_code == 403


async def test_dispatcher_cannot_create_user(client: AsyncClient) -> None:
    access, _, _ = await _register(client, "dispatcher")

    resp = await client.post(
        "/api/v1/admin/users",
        headers={"Authorization": f"Bearer {access}"},
        json={
            "email": _email("created"),
            "password": "Whatever123",
            "full_name": "Should Fail",
            "role": "driver",
        },
    )
    assert resp.status_code == 403


async def test_admin_can_create_user(client: AsyncClient) -> None:
    access, _, _ = await _register(client, "admin")

    new_email = _email("by_admin")
    resp = await client.post(
        "/api/v1/admin/users",
        headers={"Authorization": f"Bearer {access}"},
        json={
            "email": new_email,
            "password": "Whatever123",
            "full_name": "Created By Admin",
            "role": "driver",
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["email"] == new_email
    assert body["role"] == "driver"


async def test_driver_cannot_plan_route(client: AsyncClient) -> None:
    access, _, _ = await _register(client, "driver")

    resp = await client.post(
        "/api/v1/routes",
        headers={"Authorization": f"Bearer {access}"},
        json={
            "vehicle_id": str(uuid.uuid4()),
            "origin_lat": 50.45,
            "origin_lng": 30.52,
            "destination_lat": 50.46,
            "destination_lng": 30.55,
        },
    )
    assert resp.status_code == 403


async def test_driver_cannot_resolve_incident(client: AsyncClient) -> None:
    access, _, _ = await _register(client, "driver")

    resp = await client.patch(
        f"/api/v1/incidents/{uuid.uuid4()}/resolve",
        headers={"Authorization": f"Bearer {access}"},
    )
    assert resp.status_code == 403
