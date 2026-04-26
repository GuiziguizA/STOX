"""Tests d'intégration — routes /api/v1/users/* + /roles + /permissions

Prérequis : idem test_auth_routes.py
"""
import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


# ── Helpers ───────────────────────────────────────────────────────────────────

def _csrf(client: AsyncClient) -> dict:
    token = client.cookies.get("cc_csrf") or ""
    return {"x-csrf-token": token}


async def _login_as(client: AsyncClient, user: dict) -> None:
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": user["email"], "password": user["password"]},
    )
    assert r.status_code == 200


# ── GET /users ────────────────────────────────────────────────────────────────

async def test_list_users_admin(client, admin_user):
    await _login_as(client, admin_user)
    r = await client.get("/api/v1/users")
    assert r.status_code == 200
    data = r.json()
    assert "items" in data
    assert "total" in data


async def test_list_users_forbidden_for_regular_user(client, active_user):
    await _login_as(client, active_user)
    r = await client.get("/api/v1/users")
    assert r.status_code == 403


async def test_list_users_unauthenticated(client):
    r = await client.get("/api/v1/users")
    assert r.status_code == 401


async def test_list_users_pagination(client, admin_user):
    await _login_as(client, admin_user)
    r = await client.get("/api/v1/users?page=1&page_size=2")
    assert r.status_code == 200
    data = r.json()
    assert data["page"] == 1
    assert data["page_size"] == 2
    assert len(data["items"]) <= 2


# ── GET /users/{id} ───────────────────────────────────────────────────────────

async def test_get_user_admin(client, admin_user, active_user):
    await _login_as(client, admin_user)
    r = await client.get(f"/api/v1/users/{active_user['id']}")
    assert r.status_code == 200
    assert r.json()["email"] == active_user["email"]


async def test_get_user_not_found(client, admin_user):
    await _login_as(client, admin_user)
    import uuid
    r = await client.get(f"/api/v1/users/{uuid.uuid4()}")
    assert r.status_code == 404


# ── POST /users/invite ────────────────────────────────────────────────────────

async def test_invite_user(client, admin_user):
    await _login_as(client, admin_user)
    import os
    email = f"invited-{os.urandom(4).hex()}@test.com"
    r = await client.post(
        "/api/v1/users/invite",
        json={"email": email, "first_name": "Invité"},
        headers=_csrf(client),
    )
    assert r.status_code == 201
    data = r.json()
    assert data["email"] == email
    assert data["status"] == "pending"


async def test_invite_user_duplicate(client, admin_user, active_user):
    await _login_as(client, admin_user)
    r = await client.post(
        "/api/v1/users/invite",
        json={"email": active_user["email"]},
        headers=_csrf(client),
    )
    assert r.status_code == 409


async def test_invite_user_no_permission(client, active_user):
    await _login_as(client, active_user)
    r = await client.post(
        "/api/v1/users/invite",
        json={"email": "target@test.com"},
        headers=_csrf(client),
    )
    assert r.status_code == 403


# ── PATCH /users/{id} ────────────────────────────────────────────────────────

async def test_update_user_profile(client, admin_user, active_user):
    await _login_as(client, admin_user)
    r = await client.patch(
        f"/api/v1/users/{active_user['id']}",
        json={"profile": {"first_name": "Modifié"}},
        headers=_csrf(client),
    )
    assert r.status_code == 200
    assert r.json()["profile"]["first_name"] == "Modifié"


# ── PATCH /users/{id}/status ──────────────────────────────────────────────────

async def test_suspend_user(client, admin_user, active_user):
    await _login_as(client, admin_user)
    r = await client.patch(
        f"/api/v1/users/{active_user['id']}/status",
        json={"status": "suspended"},
        headers=_csrf(client),
    )
    assert r.status_code == 200
    assert r.json()["status"] == "suspended"


async def test_cannot_set_pending_status(client, admin_user, active_user):
    await _login_as(client, admin_user)
    r = await client.patch(
        f"/api/v1/users/{active_user['id']}/status",
        json={"status": "pending"},
        headers=_csrf(client),
    )
    assert r.status_code == 422


# ── PATCH /users/{id}/roles ───────────────────────────────────────────────────

async def test_assign_role_revokes_target_sessions(client, admin_user, active_user, db_session):
    """Changement de rôle doit révoquer les sessions de la cible."""
    from app.models.auth import AuthSession
    from app.services.session import create_session

    target_session, _ = await create_session(db_session, active_user["id"])
    await db_session.flush()

    await _login_as(client, admin_user)
    r = await client.patch(
        f"/api/v1/users/{active_user['id']}/roles",
        json={"role_codes": ["support"]},
        headers=_csrf(client),
    )
    assert r.status_code == 200

    from sqlalchemy import select
    result = await db_session.execute(
        select(AuthSession).where(AuthSession.id == target_session.id)
    )
    revoked = result.scalar_one()
    assert revoked.revoked_at is not None, "La session de la cible doit être révoquée"


async def test_assign_invalid_role(client, admin_user, active_user):
    await _login_as(client, admin_user)
    r = await client.patch(
        f"/api/v1/users/{active_user['id']}/roles",
        json={"role_codes": ["nonexistent_role"]},
        headers=_csrf(client),
    )
    assert r.status_code == 422


# ── GET /roles ────────────────────────────────────────────────────────────────

async def test_list_roles_admin(client, admin_user):
    await _login_as(client, admin_user)
    r = await client.get("/api/v1/roles")
    assert r.status_code == 200
    roles = r.json()
    assert isinstance(roles, list)
    codes = {role["code"] for role in roles}
    assert {"admin", "manager", "support", "user"}.issubset(codes)


async def test_list_roles_forbidden(client, active_user):
    await _login_as(client, active_user)
    r = await client.get("/api/v1/roles")
    assert r.status_code == 403


# ── GET /permissions ──────────────────────────────────────────────────────────

async def test_list_permissions_admin(client, admin_user):
    await _login_as(client, admin_user)
    r = await client.get("/api/v1/permissions")
    assert r.status_code == 200
    perms = r.json()
    assert len(perms) == 8
    codes = {p["code"] for p in perms}
    assert "users.read" in codes


async def test_list_permissions_forbidden(client, active_user):
    await _login_as(client, active_user)
    r = await client.get("/api/v1/permissions")
    assert r.status_code == 403
