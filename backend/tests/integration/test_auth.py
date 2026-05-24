import uuid

import pytest
from httpx import AsyncClient


def _unique_email(prefix: str = "test") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}@routeiq.io"


async def _register(client: AsyncClient, data: dict) -> object:
    return await client.post("/api/v1/auth/register", json=data)


async def _login(client: AsyncClient, email: str, password: str) -> object:
    return await client.post("/api/v1/auth/login", json={
        "email": email,
        "password": password,
    })


async def test_register_new_user_returns_201(client: AsyncClient) -> None:
    email = _unique_email("reg")
    resp = await _register(client, {
        "email": email,
        "password": "Passw0rd!",
        "full_name": "New User",
        "role": "driver",
    })
    assert resp.status_code == 201
    body = resp.json()
    assert body["email"] == email
    assert body["full_name"] == "New User"
    assert body["role"] == "driver"
    assert body["is_active"] is True
    assert "id" in body
    assert "created_at" in body


async def test_register_duplicate_email_returns_409(client: AsyncClient) -> None:
    email = _unique_email("dup")
    data = {
        "email": email,
        "password": "Passw0rd!",
        "full_name": "First User",
        "role": "driver",
    }
    resp1 = await _register(client, data)
    assert resp1.status_code == 201

    resp2 = await _register(client, data)
    assert resp2.status_code == 409
    assert "already registered" in resp2.json()["detail"]


async def test_login_valid_credentials_returns_token(client: AsyncClient) -> None:
    email = _unique_email("login")
    password = "StrongP@ss123"
    await _register(client, {
        "email": email,
        "password": password,
        "full_name": "Login User",
        "role": "dispatcher",
    })

    resp = await _login(client, email, password)
    assert resp.status_code == 200
    body = resp.json()
    assert "access_token" in body
    assert body["token_type"] == "bearer"
    assert len(body["access_token"]) > 0


async def test_login_invalid_password_returns_401(client: AsyncClient) -> None:
    email = _unique_email("bad_pw")
    await _register(client, {
        "email": email,
        "password": "CorrectP@ss",
        "full_name": "Bad PW",
        "role": "driver",
    })

    resp = await _login(client, email, "WrongPassword")
    assert resp.status_code == 401
    assert "Invalid" in resp.json()["detail"]


async def test_me_with_valid_token_returns_user(client: AsyncClient) -> None:
    email = _unique_email("me")
    password = "Passw0rd!"
    await _register(client, {
        "email": email,
        "password": password,
        "full_name": "Me Test",
        "role": "admin",
    })
    login_resp = await _login(client, email, password)
    token = login_resp.json()["access_token"]

    resp = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["email"] == email
    assert body["full_name"] == "Me Test"
    assert body["role"] == "admin"


async def test_me_without_token_returns_401(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/auth/me")
    assert resp.status_code == 401
