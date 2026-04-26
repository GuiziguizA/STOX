"""Routes RGPD — /users/me/delete-account + /users/me/export"""
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import get_current_session, get_current_user, require_csrf
from app.models.audit import AuditEventType, AuditLog
from app.models.auth import AuthSession
from app.models.user import Profile, User, UserStatus
from app.schemas.common import MessageOut
from app.services.audit import record_audit_event
from app.services.email import send_deletion_email
from app.services.session import clear_auth_cookies, revoke_all_sessions

router = APIRouter(prefix="/users/me", tags=["gdpr"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


# ── POST /users/me/delete-account ────────────────────────────────────────────

@router.post("/delete-account", response_model=MessageOut)
async def delete_account(
    request: Request,
    response: Response,
    session: Annotated[AuthSession, Depends(get_current_session)],
    db: Annotated[AsyncSession, Depends(get_db)],
    _csrf: Annotated[None, Depends(require_csrf)],
):
    result = await db.execute(select(User).where(User.id == session.user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Utilisateur introuvable")

    if user.status == UserStatus.deleted:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Compte déjà supprimé")

    original_email = str(user.email)
    user.status = UserStatus.deleted
    user.email = f"deleted+{user.id}@deleted.invalid"
    user.deleted_at = _now()
    user.updated_at = _now()

    await revoke_all_sessions(db, user.id)

    await record_audit_event(
        db,
        AuditEventType.user_deleted,
        actor_id=user.id,
        target_id=user.id,
        payload={"method": "self_delete"},
        ip_address=_client_ip(request),
    )
    await db.commit()

    try:
        await send_deletion_email(original_email)
    except Exception:
        pass

    clear_auth_cookies(response)
    return MessageOut(message="Compte supprimé. Vous serez déconnecté.")


# ── GET /users/me/export ──────────────────────────────────────────────────────

@router.get("/export")
async def export_data(
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AuthSession, Depends(get_current_session)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    profile_result = await db.execute(select(Profile).where(Profile.user_id == user.id))
    profile = profile_result.scalar_one_or_none()

    sessions_result = await db.execute(
        select(AuthSession)
        .where(AuthSession.user_id == user.id)
        .order_by(AuthSession.created_at.desc())
    )
    sessions = sessions_result.scalars().all()

    audit_result = await db.execute(
        select(AuditLog)
        .where(AuditLog.target_user_id == user.id)
        .order_by(AuditLog.created_at.desc())
    )
    audit_logs = audit_result.scalars().all()

    await record_audit_event(
        db,
        AuditEventType.user_data_exported,
        actor_id=user.id,
        target_id=user.id,
        ip_address=_client_ip(request),
    )
    await db.commit()

    data = {
        "exported_at": _now().isoformat(),
        "profile": {
            "id": str(user.id),
            "email": user.email,
            "status": user.status.value,
            "email_verified_at": user.email_verified_at.isoformat() if user.email_verified_at else None,
            "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
            "created_at": user.created_at.isoformat(),
            "first_name": profile.first_name if profile else None,
            "last_name": profile.last_name if profile else None,
            "locale": profile.locale if profile else "fr-FR",
            "timezone": profile.timezone if profile else "Europe/Paris",
        },
        "sessions": [
            {
                "id": str(s.id),
                "created_at": s.created_at.isoformat(),
                "last_seen_at": s.last_seen_at.isoformat(),
                "expires_at": s.expires_at.isoformat(),
                "revoked_at": s.revoked_at.isoformat() if s.revoked_at else None,
                "ip_address": s.ip_address,
                "user_agent": s.user_agent,
            }
            for s in sessions
        ],
        "audit_logs": [
            {
                "id": log.id,
                "event_type": log.event_type.value,
                "created_at": log.created_at.isoformat(),
                "ip_address": log.ip_address,
                "payload": log.payload_json,
            }
            for log in audit_logs
        ],
    }

    return JSONResponse(
        content=data,
        headers={
            "Content-Disposition": f'attachment; filename="export-{user.id}.json"',
            "Content-Type": "application/json",
        },
    )
