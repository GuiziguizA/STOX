"""Tests d'intégration — routes /api/v1/auth/*

Prérequis :
  docker compose up -d db cache
  DATABASE_URL=postgresql://postgres:changeme@localhost:5432/projet_action_test \
  REDIS_URL=redis://localhost:6379/1 \
  pytest tests/test_auth_routes.py -v
"""
import pytest
import pytest_asyncio
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


# ── Helpers ───────────────────────────────────────────────────────────────────

def _csrf_headers(client: AsyncClient) -> dict:
    csrf = client.cookies.get("cc_csrf") or ""
    return {"x-csrf-token": csrf}


async def _login(client: AsyncClient, email: str, password: str) -> dict:
    r = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()


# ── Register ──────────────────────────────────────────────────────────────────

async def test_register_happy_path(client):
    r = await client.post(
        "/api/v1/auth/register",
        json={"email": "newuser@test.com", "password": "StrongPass1!"},
    )
    assert r.status_code == 201
    data = r.json()
    assert data["email"] == "newuser@test.com"
    assert data["status"] == "pending"
    assert "cc_session" in client.cookies


async def test_register_duplicate_email(client, active_user):
    r = await client.post(
        "/api/v1/auth/register",
        json={"email": active_user["email"], "password": "SomePass1!"},
    )
    assert r.status_code == 409


async def test_register_weak_password(client):
    r = await client.post(
        "/api/v1/auth/register",
        json={"email": "weak@test.com", "password": "short"},
    )
    assert r.status_code == 422


# ── Login ─────────────────────────────────────────────────────────────────────

async def test_login_happy_path(client, active_user):
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": active_user["email"], "password": active_user["password"]},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["email"] == active_user["email"]
    assert "cc_session" in client.cookies
    assert "cc_csrf" in client.cookies


async def test_login_wrong_password(client, active_user):
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": active_user["email"], "password": "wrongpass"},
    )
    assert r.status_code == 401


async def test_login_unknown_email(client):
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": "nobody@test.com", "password": "whatever"},
    )
    assert r.status_code == 401


async def test_login_rate_limit(client):
    """6e login en 15 min retourne 429."""
    for _ in range(6):
        r = await client.post(
            "/api/v1/auth/login",
            json={"email": "rate@test.com", "password": "wrongpassword"},
        )
    assert r.status_code == 429


# ── Me ────────────────────────────────────────────────────────────────────────

async def test_me_authenticated(client, active_user):
    await _login(client, active_user["email"], active_user["password"])
    r = await client.get("/api/v1/auth/me")
    assert r.status_code == 200
    assert r.json()["email"] == active_user["email"]


async def test_me_unauthenticated(client):
    r = await client.get("/api/v1/auth/me")
    assert r.status_code == 401


# ── Logout ────────────────────────────────────────────────────────────────────

async def test_logout(client, active_user):
    await _login(client, active_user["email"], active_user["password"])
    r = await client.post("/api/v1/auth/logout")
    assert r.status_code == 200
    assert "cc_session" not in client.cookies or client.cookies.get("cc_session") == ""

    r2 = await client.get("/api/v1/auth/me")
    assert r2.status_code == 401


# ── Logout-all ────────────────────────────────────────────────────────────────

async def test_logout_all(client, active_user):
    await _login(client, active_user["email"], active_user["password"])
    headers = _csrf_headers(client)
    r = await client.post("/api/v1/auth/logout-all", headers=headers)
    assert r.status_code == 200


async def test_logout_all_requires_csrf(client, active_user):
    await _login(client, active_user["email"], active_user["password"])
    r = await client.post("/api/v1/auth/logout-all")
    assert r.status_code == 403


# ── Sessions ──────────────────────────────────────────────────────────────────

async def test_list_sessions(client, active_user):
    await _login(client, active_user["email"], active_user["password"])
    r = await client.get("/api/v1/auth/sessions")
    assert r.status_code == 200
    sessions = r.json()
    assert isinstance(sessions, list)
    assert len(sessions) >= 1


async def test_revoke_session(client, active_user):
    await _login(client, active_user["email"], active_user["password"])
    sessions_r = await client.get("/api/v1/auth/sessions")
    sessions = sessions_r.json()
    session_id = sessions[0]["id"]

    headers = _csrf_headers(client)
    r = await client.delete(f"/api/v1/auth/sessions/{session_id}", headers=headers)
    assert r.status_code == 200


# ── Verify email ──────────────────────────────────────────────────────────────

async def test_verify_email_invalid_token(client):
    r = await client.post("/api/v1/auth/verify-email", json={"token": "ab" * 32})
    assert r.status_code in (404, 422)


async def test_verify_email_bad_format(client):
    r = await client.post("/api/v1/auth/verify-email", json={"token": "not_hex"})
    assert r.status_code == 422


# ── Forgot / Reset password ───────────────────────────────────────────────────

async def test_forgot_password_always_200(client):
    r = await client.post(
        "/api/v1/auth/forgot-password",
        json={"email": "nobody@nowhere.com"},
    )
    assert r.status_code == 200


async def test_reset_password_invalid_token(client):
    r = await client.post(
        "/api/v1/auth/reset-password",
        json={"token": "ab" * 32, "password": "NewPassword1!"},
    )
    assert r.status_code in (404, 422)


async def test_reset_password_revokes_sessions(client, active_user, db_session):
    """Reset password doit révoquer toutes les sessions."""
    from app.core.security import generate_token, hash_token, token_to_cookie
    from app.models.auth import PasswordResetToken
    from datetime import datetime, timezone, timedelta

    await _login(client, active_user["email"], active_user["password"])
    me_before = await client.get("/api/v1/auth/me")
    assert me_before.status_code == 200

    raw = generate_token()
    pw_token = PasswordResetToken(
        user_id=active_user["id"],
        token_hash=hash_token(raw),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    db_session.add(pw_token)
    await db_session.flush()

    r = await client.post(
        "/api/v1/auth/reset-password",
        json={"token": token_to_cookie(raw), "password": "NewPassword2!"},
    )
    assert r.status_code == 200

    me_after = await client.get("/api/v1/auth/me")
    assert me_after.status_code == 401
