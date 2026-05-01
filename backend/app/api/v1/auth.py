"""Routes d'authentification — /auth/*"""
import logging
from datetime import datetime, timezone
from typing import Annotated

import uuid

logger = logging.getLogger(__name__)
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.db import get_db
from app.core.deps import get_current_session, get_current_user, require_csrf
from app.core.redis import check_rate_limit, get_redis
from app.core.security import (
    generate_token,
    hash_password,
    hash_token,
    password_needs_rehash,
    token_to_cookie,
    verify_password,
)
from app.models.auth import AuthSession, EmailVerificationToken, PasswordResetToken
from app.models.audit import AuditEventType
from app.models.user import Profile, User, UserStatus
from app.schemas.auth import (
    ForgotPasswordIn,
    LoginIn,
    RegisterIn,
    ResendVerificationIn,
    ResetPasswordIn,
    SessionOut,
    VerifyEmailIn,
)
from app.schemas.common import MessageOut
from app.schemas.user import UserOut
from app.services.audit import record_audit_event
from app.services.email import send_password_reset_email, send_verification_email, send_welcome_email
from app.services.session import (
    clear_auth_cookies,
    create_session,
    revoke_all_sessions,
    revoke_all_sessions_except,
    revoke_session,
    set_csrf_cookie,
    set_session_cookie,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


def _user_agent(request: Request) -> str | None:
    return request.headers.get("user-agent")


def _load_user_full(user_id):
    return (
        select(User)
        .where(User.id == user_id)
        .options(
            selectinload(User.profile),
            selectinload(User.user_roles)
            .selectinload("role")
            .selectinload("role_permissions")
            .selectinload("permission"),
        )
    )


async def _get_full_user(db: AsyncSession, user_id) -> User:
    result = await db.execute(_load_user_full(user_id))
    return result.scalar_one()


# ── POST /auth/register ───────────────────────────────────────────────────────

@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def register(
    body: RegisterIn,
    request: Request,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    r = get_redis()
    ip = _client_ip(request)
    rl_key = f"rl:register:{ip}"
    # 3 inscriptions / heure par IP
    allowed = await check_rate_limit(r, rl_key, capacity=3, rate_per_second=3 / 3600)
    if not allowed:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Trop de tentatives — réessayez plus tard")

    existing = await db.execute(select(User).where(User.email == body.email))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email déjà utilisé")

    user = User(
        email=body.email,
        password_hash=hash_password(body.password),
        status=UserStatus.pending,
    )
    db.add(user)
    await db.flush()

    profile = Profile(
        user_id=user.id,
        first_name=body.first_name,
        last_name=body.last_name,
    )
    db.add(profile)

    raw_token = generate_token()
    ev_token = EmailVerificationToken(
        user_id=user.id,
        token_hash=hash_token(raw_token),
        expires_at=_now().replace(microsecond=0),
    )
    # 24h d'expiration pour le token de vérif email
    from datetime import timedelta
    ev_token.expires_at = _now() + timedelta(hours=24)
    db.add(ev_token)

    await record_audit_event(
        db,
        AuditEventType.user_register,
        actor_id=user.id,
        target_id=user.id,
        ip_address=ip,
        user_agent=_user_agent(request),
    )

    session, cookie_val = await create_session(
        db, user.id, ip_address=ip, user_agent=_user_agent(request)
    )
    await db.commit()

    await send_verification_email(user.email, token_to_cookie(raw_token))

    set_session_cookie(response, cookie_val)
    set_csrf_cookie(response)

    full_user = await _get_full_user(db, user.id)
    return UserOut.from_user(full_user)


# ── POST /auth/login ──────────────────────────────────────────────────────────

@router.post("/login", response_model=UserOut)
async def login(
    body: LoginIn,
    request: Request,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    r = get_redis()
    ip = _client_ip(request)
    rl_key = f"rl:login:{ip}:{body.email}"
    # 5 tentatives / 15 min par IP+email
    allowed = await check_rate_limit(r, rl_key, capacity=5, rate_per_second=5 / 900)
    if not allowed:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Trop de tentatives — réessayez dans 15 minutes")

    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()

    if user is None or not verify_password(body.password, user.password_hash):
        if user is not None:
            await record_audit_event(
                db,
                AuditEventType.user_login_failed,
                actor_id=user.id,
                target_id=user.id,
                ip_address=ip,
                user_agent=_user_agent(request),
            )
            await db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Email ou mot de passe incorrect")

    if user.status == UserStatus.suspended:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Compte suspendu")
    if user.status == UserStatus.deleted:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Compte supprimé")

    if password_needs_rehash(user.password_hash):
        user.password_hash = hash_password(body.password)

    user.last_login_at = _now()

    session, cookie_val = await create_session(
        db, user.id, ip_address=ip, user_agent=_user_agent(request)
    )

    await record_audit_event(
        db,
        AuditEventType.user_login,
        actor_id=user.id,
        target_id=user.id,
        ip_address=ip,
        user_agent=_user_agent(request),
    )
    await db.commit()

    set_session_cookie(response, cookie_val)
    set_csrf_cookie(response)

    full_user = await _get_full_user(db, user.id)
    return UserOut.from_user(full_user)


# ── POST /auth/logout ─────────────────────────────────────────────────────────

@router.post("/logout", response_model=MessageOut)
async def logout(
    request: Request,
    response: Response,
    session: Annotated[AuthSession, Depends(get_current_session)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    await revoke_session(db, session.id)
    await record_audit_event(
        db,
        AuditEventType.user_logout,
        actor_id=session.user_id,
        ip_address=_client_ip(request),
    )
    await db.commit()
    clear_auth_cookies(response)
    return MessageOut(message="Déconnecté")


# ── POST /auth/logout-all ─────────────────────────────────────────────────────

@router.post("/logout-all", response_model=MessageOut)
async def logout_all(
    request: Request,
    response: Response,
    session: Annotated[AuthSession, Depends(get_current_session)],
    db: Annotated[AsyncSession, Depends(get_db)],
    _csrf: Annotated[None, Depends(require_csrf)],
):
    await revoke_all_sessions_except(db, session.user_id, session.id)
    await record_audit_event(
        db,
        AuditEventType.user_logout_all,
        actor_id=session.user_id,
        ip_address=_client_ip(request),
    )
    await db.commit()
    return MessageOut(message="Toutes les autres sessions ont été révoquées")


# ── GET /auth/me ──────────────────────────────────────────────────────────────

@router.get("/me", response_model=UserOut)
async def me(
    user: Annotated[User, Depends(get_current_user)],
):
    return UserOut.from_user(user)


# ── POST /auth/verify-email ───────────────────────────────────────────────────

@router.post("/verify-email", response_model=MessageOut)
async def verify_email(
    body: VerifyEmailIn,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    from app.core.security import cookie_to_token
    raw = cookie_to_token(body.token)
    if raw is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Token invalide")

    token_h = hash_token(raw)
    result = await db.execute(
        select(EmailVerificationToken).where(EmailVerificationToken.token_hash == token_h)
    )
    ev = result.scalar_one_or_none()

    if ev is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Token introuvable")
    if ev.used_at is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Token déjà utilisé")

    exp = ev.expires_at
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    if _now() > exp:
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="Token expiré")

    ev.used_at = _now()

    result_user = await db.execute(select(User).where(User.id == ev.user_id))
    user = result_user.scalar_one()
    was_pending = user.status == UserStatus.pending
    user.email_verified_at = _now()
    if was_pending:
        user.status = UserStatus.active

    await record_audit_event(db, AuditEventType.user_email_verified, actor_id=user.id, target_id=user.id)
    await db.commit()

    if was_pending:
        from sqlalchemy.orm import selectinload
        result2 = await db.execute(
            select(User).where(User.id == user.id).options(selectinload(User.profile))
        )
        u2 = result2.scalar_one()
        first_name = u2.profile.first_name if u2.profile else None
        try:
            await send_welcome_email(user.email, first_name)
        except Exception:
            logger.exception("Echec envoi welcome email a %s", user.email)

    return MessageOut(message="Email vérifié")


# ── POST /auth/resend-verification ───────────────────────────────────────────

@router.post("/resend-verification", response_model=MessageOut)
async def resend_verification(
    request: Request,
    session: Annotated[AuthSession, Depends(get_current_session)],
    db: Annotated[AsyncSession, Depends(get_db)],
    _csrf: Annotated[None, Depends(require_csrf)],
):
    r = get_redis()
    rl_key = f"rl:resend-verif:{session.user_id}"
    allowed = await check_rate_limit(r, rl_key, capacity=3, rate_per_second=3 / 3600)
    if not allowed:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Trop de demandes")

    result = await db.execute(select(User).where(User.id == session.user_id))
    user = result.scalar_one()

    if user.email_verified_at is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email déjà vérifié")

    from datetime import timedelta
    raw_token = generate_token()
    ev = EmailVerificationToken(
        user_id=user.id,
        token_hash=hash_token(raw_token),
        expires_at=_now() + timedelta(hours=24),
    )
    db.add(ev)
    await db.commit()

    await send_verification_email(user.email, token_to_cookie(raw_token))
    return MessageOut(message="Email de vérification envoyé")


# ── POST /auth/forgot-password ────────────────────────────────────────────────

@router.post("/forgot-password", response_model=MessageOut)
async def forgot_password(
    body: ForgotPasswordIn,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    r = get_redis()
    rl_key = f"rl:forgot-pwd:{body.email}"
    allowed = await check_rate_limit(r, rl_key, capacity=3, rate_per_second=3 / 3600)
    if not allowed:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Trop de demandes")

    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()

    # Toujours 200 pour ne pas divulguer l'existence du compte
    if user and user.status == UserStatus.active:
        from datetime import timedelta
        raw_token = generate_token()
        pw_token = PasswordResetToken(
            user_id=user.id,
            token_hash=hash_token(raw_token),
            expires_at=_now() + timedelta(hours=1),
        )
        db.add(pw_token)
        await record_audit_event(
            db,
            AuditEventType.user_password_reset_requested,
            actor_id=user.id,
            target_id=user.id,
            ip_address=_client_ip(request),
        )
        await db.commit()
        await send_password_reset_email(user.email, token_to_cookie(raw_token))

    return MessageOut(message="Si cet email existe, un lien de réinitialisation a été envoyé")


# ── POST /auth/reset-password ─────────────────────────────────────────────────

@router.post("/reset-password", response_model=MessageOut)
async def reset_password(
    body: ResetPasswordIn,
    request: Request,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    from app.core.security import cookie_to_token
    raw = cookie_to_token(body.token)
    if raw is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Token invalide")

    token_h = hash_token(raw)
    result = await db.execute(
        select(PasswordResetToken).where(PasswordResetToken.token_hash == token_h)
    )
    pw_token = result.scalar_one_or_none()

    if pw_token is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Token introuvable")
    if pw_token.used_at is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Token déjà utilisé")

    exp = pw_token.expires_at
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    if _now() > exp:
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="Token expiré")

    pw_token.used_at = _now()

    result_user = await db.execute(select(User).where(User.id == pw_token.user_id))
    user = result_user.scalar_one()
    user.password_hash = hash_password(body.password)

    # Révoquer TOUTES les sessions (paranoia)
    await revoke_all_sessions(db, user.id)

    await record_audit_event(
        db,
        AuditEventType.user_password_reset_completed,
        actor_id=user.id,
        target_id=user.id,
        ip_address=_client_ip(request),
    )
    await db.commit()
    clear_auth_cookies(response)
    return MessageOut(message="Mot de passe réinitialisé. Veuillez vous reconnecter.")


# ── GET /auth/sessions ────────────────────────────────────────────────────────

@router.get("/sessions", response_model=list[SessionOut])
async def list_sessions(
    session: Annotated[AuthSession, Depends(get_current_session)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    now = _now()
    result = await db.execute(
        select(AuthSession).where(
            AuthSession.user_id == session.user_id,
            AuthSession.revoked_at.is_(None),
            AuthSession.expires_at > now,
        )
    )
    sessions = result.scalars().all()
    return [SessionOut.model_validate(s) for s in sessions]


# ── DELETE /auth/sessions/{session_id} ───────────────────────────────────────

@router.delete("/sessions/{session_id}", response_model=MessageOut)
async def revoke_specific_session(
    session_id: uuid.UUID,
    session: Annotated[AuthSession, Depends(get_current_session)],
    db: Annotated[AsyncSession, Depends(get_db)],
    _csrf: Annotated[None, Depends(require_csrf)],
):
    result = await db.execute(
        select(AuthSession).where(
            AuthSession.id == session_id,
            AuthSession.user_id == session.user_id,
        )
    )
    target = result.scalar_one_or_none()
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session introuvable")
    if target.revoked_at is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Session déjà révoquée")

    await revoke_session(db, session_id)
    await db.commit()
    return MessageOut(message="Session révoquée")
