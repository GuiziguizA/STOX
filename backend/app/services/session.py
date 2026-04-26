"""Helpers de gestion de session — création, révocation, cookies."""
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Response
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import generate_token, hash_token, token_to_cookie
from app.models.auth import AuthSession


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def create_session(
    db: AsyncSession,
    user_id,
    *,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> tuple[AuthSession, str]:
    """Crée une AuthSession et retourne (session, cookie_value)."""
    raw_token = generate_token()
    token_h = hash_token(raw_token)
    now = _now()
    expires_at = now + timedelta(seconds=settings.session_max_age_seconds)
    idle_expires_at = now + timedelta(seconds=settings.session_idle_seconds)

    session = AuthSession(
        user_id=user_id,
        token_hash=token_h,
        expires_at=expires_at,
        idle_expires_at=idle_expires_at,
        last_seen_at=now,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    db.add(session)
    await db.flush()
    return session, token_to_cookie(raw_token)


def set_session_cookie(response: Response, cookie_value: str) -> None:
    response.set_cookie(
        key=settings.session_cookie_name,
        value=cookie_value,
        max_age=settings.session_max_age_seconds,
        httponly=True,
        samesite="lax",
        secure=settings.is_production,
        path="/",
    )


def set_csrf_cookie(response: Response) -> str:
    csrf_token = secrets.token_hex(32)
    response.set_cookie(
        key=settings.csrf_cookie_name,
        value=csrf_token,
        max_age=settings.session_max_age_seconds,
        httponly=False,
        samesite="lax",
        secure=settings.is_production,
        path="/",
    )
    return csrf_token


def clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(key=settings.session_cookie_name, path="/")
    response.delete_cookie(key=settings.csrf_cookie_name, path="/")


async def revoke_session(db: AsyncSession, session_id) -> None:
    await db.execute(
        update(AuthSession)
        .where(AuthSession.id == session_id)
        .values(revoked_at=_now())
    )


async def revoke_all_sessions_except(db: AsyncSession, user_id, except_session_id) -> None:
    """Révoque toutes les sessions actives de l'user sauf celle en cours."""
    await db.execute(
        update(AuthSession)
        .where(
            AuthSession.user_id == user_id,
            AuthSession.id != except_session_id,
            AuthSession.revoked_at.is_(None),
        )
        .values(revoked_at=_now())
    )


async def revoke_all_sessions(db: AsyncSession, user_id) -> None:
    """Révoque TOUTES les sessions actives de l'user (ex. reset password)."""
    await db.execute(
        update(AuthSession)
        .where(
            AuthSession.user_id == user_id,
            AuthSession.revoked_at.is_(None),
        )
        .values(revoked_at=_now())
    )
