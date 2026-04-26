import secrets
import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import Cookie, Depends, Header, HTTPException, Request, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.db import get_db
from app.core.security import cookie_to_token, hash_token
from app.models.auth import AuthSession
from app.models.user import User, UserStatus


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def get_current_session(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AuthSession:
    raw_cookie = request.cookies.get(settings.session_cookie_name)
    if not raw_cookie:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Non authentifié")

    token_bytes = cookie_to_token(raw_cookie)
    if token_bytes is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Cookie invalide")

    token_hash = hash_token(token_bytes)
    now = _now()

    result = await db.execute(
        select(AuthSession).where(AuthSession.token_hash == token_hash)
    )
    session = result.scalar_one_or_none()

    if session is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session introuvable")

    if session.revoked_at is not None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session révoquée")

    expires_at = session.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if now > expires_at:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expirée")

    idle_expires_at = session.idle_expires_at
    if idle_expires_at.tzinfo is None:
        idle_expires_at = idle_expires_at.replace(tzinfo=timezone.utc)
    if now > idle_expires_at:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session idle expirée")

    # Refresh last_seen_at et idle_expires_at
    from datetime import timedelta
    new_idle = now + timedelta(seconds=settings.session_idle_seconds)
    await db.execute(
        update(AuthSession)
        .where(AuthSession.id == session.id)
        .values(last_seen_at=now, idle_expires_at=new_idle)
    )
    await db.commit()

    return session


async def get_current_user(
    session: Annotated[AuthSession, Depends(get_current_session)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    result = await db.execute(
        select(User)
        .where(User.id == session.user_id)
        .options(
            selectinload(User.profile),
            selectinload(User.user_roles)
            .selectinload("role")
            .selectinload("role_permissions")
            .selectinload("permission"),
        )
    )
    user = result.scalar_one_or_none()

    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Utilisateur introuvable")

    if user.status != UserStatus.active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Compte {user.status.value}",
        )

    return user


def _get_user_permissions(user: User) -> set[str]:
    return {
        rp.permission.code
        for ur in user.user_roles
        for rp in ur.role.role_permissions
    }


def require_permission(permission_code: str):
    """Builder de dépendance FastAPI : vérifie qu'un user a la permission."""

    async def _check(user: Annotated[User, Depends(get_current_user)]) -> User:
        if permission_code not in _get_user_permissions(user):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission '{permission_code}' requise",
            )
        return user

    return _check


async def require_csrf(
    request: Request,
) -> None:
    """Double-submit cookie CSRF check — s'applique aux mutations uniquement."""
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return

    cookie_token = request.cookies.get(settings.csrf_cookie_name)
    header_token = request.headers.get(settings.csrf_header_name)

    if not cookie_token or not header_token:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Token CSRF manquant",
        )

    # Comparaison time-safe
    if not secrets.compare_digest(cookie_token, header_token):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Token CSRF invalide",
        )
