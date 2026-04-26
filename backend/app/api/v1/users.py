"""Routes admin users — /users/*  (require_permission)"""
import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.db import get_db
from app.core.deps import get_current_session, get_current_user, require_csrf, require_permission
from app.core.security import generate_token, hash_password, hash_token, token_to_cookie
from app.models.audit import AuditEventType
from app.models.auth import AuthSession, EmailVerificationToken
from app.models.user import Profile, Role, User, UserRole, UserStatus
from app.schemas.common import MessageOut, PaginatedOut
from app.schemas.user import UserInviteIn, UserOut, UserRolesUpdateIn, UserStatusUpdateIn, UserUpdateIn
from app.services.audit import record_audit_event
from app.services.email import send_invite_email
from app.services.session import revoke_all_sessions

router = APIRouter(prefix="/users", tags=["users"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


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


async def _get_full_user_or_404(db: AsyncSession, user_id: uuid.UUID) -> User:
    result = await db.execute(_load_user_full(user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Utilisateur introuvable")
    return user


def _client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


# ── GET /users ────────────────────────────────────────────────────────────────

@router.get("", response_model=PaginatedOut[UserOut])
async def list_users(
    db: Annotated[AsyncSession, Depends(get_db)],
    _actor: Annotated[User, Depends(require_permission("users.read"))],
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=50),
    status_filter: UserStatus | None = Query(default=None, alias="status"),
    search: str | None = Query(default=None, max_length=200),
    role: str | None = Query(default=None),
):
    base_query = (
        select(User)
        .options(
            selectinload(User.profile),
            selectinload(User.user_roles)
            .selectinload("role")
            .selectinload("role_permissions")
            .selectinload("permission"),
        )
        .where(User.status != UserStatus.deleted)
    )

    if status_filter:
        base_query = base_query.where(User.status == status_filter)

    if search:
        pattern = f"%{search}%"
        base_query = base_query.where(User.email.ilike(pattern))

    if role:
        base_query = base_query.join(User.user_roles).join(UserRole.role).where(Role.code == role)

    total_result = await db.execute(select(func.count()).select_from(base_query.subquery()))
    total = total_result.scalar_one()

    offset = (page - 1) * page_size
    result = await db.execute(
        base_query.order_by(User.created_at.desc()).offset(offset).limit(page_size)
    )
    users = result.scalars().unique().all()

    return PaginatedOut(
        items=[UserOut.from_user(u) for u in users],
        total=total,
        page=page,
        page_size=page_size,
    )


# ── GET /users/{user_id} ──────────────────────────────────────────────────────

@router.get("/{user_id}", response_model=UserOut)
async def get_user(
    user_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _actor: Annotated[User, Depends(require_permission("users.read"))],
):
    user = await _get_full_user_or_404(db, user_id)
    return UserOut.from_user(user)


# ── POST /users/invite ────────────────────────────────────────────────────────

@router.post("/invite", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def invite_user(
    body: UserInviteIn,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    actor: Annotated[User, Depends(require_permission("users.invite"))],
    _csrf: Annotated[None, Depends(require_csrf)],
):
    existing = await db.execute(select(User).where(User.email == body.email))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email déjà utilisé")

    import secrets
    temp_password = secrets.token_hex(16)
    user = User(
        email=body.email,
        password_hash=hash_password(temp_password),
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

    if body.role_codes:
        roles_result = await db.execute(
            select(Role).where(Role.code.in_(body.role_codes))
        )
        roles = roles_result.scalars().all()
        found_codes = {r.code for r in roles}
        missing = set(body.role_codes) - found_codes
        if missing:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Rôles introuvables : {', '.join(missing)}",
            )
        for role in roles:
            db.add(UserRole(user_id=user.id, role_id=role.id, assigned_by=actor.id))

    from datetime import timedelta
    raw_token = generate_token()
    ev = EmailVerificationToken(
        user_id=user.id,
        token_hash=hash_token(raw_token),
        expires_at=_now() + timedelta(days=7),
    )
    db.add(ev)

    await record_audit_event(
        db,
        AuditEventType.user_register,
        actor_id=actor.id,
        target_id=user.id,
        payload={"invited_by": str(actor.id)},
        ip_address=_client_ip(request),
    )
    await db.commit()

    await send_invite_email(
        user.email,
        token_to_cookie(raw_token),
        invited_by=actor.email,
    )

    full_user = await _get_full_user_or_404(db, user.id)
    return UserOut.from_user(full_user)


# ── PATCH /users/{user_id} ────────────────────────────────────────────────────

@router.patch("/{user_id}", response_model=UserOut)
async def update_user(
    user_id: uuid.UUID,
    body: UserUpdateIn,
    db: Annotated[AsyncSession, Depends(get_db)],
    _actor: Annotated[User, Depends(require_permission("users.write"))],
    _csrf: Annotated[None, Depends(require_csrf)],
):
    user = await _get_full_user_or_404(db, user_id)

    if body.email is not None and body.email != user.email:
        dup = await db.execute(select(User).where(User.email == body.email, User.id != user_id))
        if dup.scalar_one_or_none() is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email déjà utilisé")
        user.email = body.email
        user.email_verified_at = None

    if body.profile is not None:
        if user.profile is None:
            db.add(Profile(user_id=user.id))
            await db.flush()
            result = await db.execute(_load_user_full(user_id))
            user = result.scalar_one()

        p = user.profile
        if body.profile.first_name is not None:
            p.first_name = body.profile.first_name
        if body.profile.last_name is not None:
            p.last_name = body.profile.last_name
        if body.profile.locale is not None:
            p.locale = body.profile.locale
        if body.profile.timezone is not None:
            p.timezone = body.profile.timezone

    user.updated_at = _now()
    await db.commit()

    full_user = await _get_full_user_or_404(db, user_id)
    return UserOut.from_user(full_user)


# ── PATCH /users/{user_id}/status ─────────────────────────────────────────────

@router.patch("/{user_id}/status", response_model=UserOut)
async def update_user_status(
    user_id: uuid.UUID,
    body: UserStatusUpdateIn,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    actor: Annotated[User, Depends(require_permission("users.suspend"))],
    _csrf: Annotated[None, Depends(require_csrf)],
):
    user = await _get_full_user_or_404(db, user_id)

    event_map = {
        UserStatus.suspended: AuditEventType.user_suspended,
        UserStatus.active: AuditEventType.user_reactivated,
        UserStatus.deleted: AuditEventType.user_deleted,
    }

    old_status = user.status
    user.status = body.status
    user.updated_at = _now()

    if body.status == UserStatus.deleted:
        user.deleted_at = _now()
        await revoke_all_sessions(db, user.id)

    if body.status == UserStatus.suspended:
        await revoke_all_sessions(db, user.id)

    await record_audit_event(
        db,
        event_map[body.status],
        actor_id=actor.id,
        target_id=user.id,
        payload={"from": old_status.value, "to": body.status.value},
        ip_address=_client_ip(request),
    )
    await db.commit()

    full_user = await _get_full_user_or_404(db, user_id)
    return UserOut.from_user(full_user)


# ── PATCH /users/{user_id}/roles ──────────────────────────────────────────────

@router.patch("/{user_id}/roles", response_model=UserOut)
async def update_user_roles(
    user_id: uuid.UUID,
    body: UserRolesUpdateIn,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    actor: Annotated[User, Depends(require_permission("roles.assign"))],
    _csrf: Annotated[None, Depends(require_csrf)],
):
    user = await _get_full_user_or_404(db, user_id)

    desired_codes = set(body.role_codes)
    roles_result = await db.execute(
        select(Role).where(Role.code.in_(desired_codes))
    )
    roles = {r.code: r for r in roles_result.scalars().all()}

    missing = desired_codes - set(roles.keys())
    if missing:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Rôles introuvables : {', '.join(missing)}",
        )

    current_roles = {ur.role.code: ur for ur in user.user_roles}
    current_codes = set(current_roles.keys())

    to_add = desired_codes - current_codes
    to_remove = current_codes - desired_codes

    for code in to_add:
        db.add(UserRole(user_id=user.id, role_id=roles[code].id, assigned_by=actor.id))
        await record_audit_event(
            db,
            AuditEventType.user_role_assigned,
            actor_id=actor.id,
            target_id=user.id,
            payload={"role": code},
            ip_address=_client_ip(request),
        )

    for code in to_remove:
        ur = current_roles[code]
        await db.delete(ur)
        await record_audit_event(
            db,
            AuditEventType.user_role_revoked,
            actor_id=actor.id,
            target_id=user.id,
            payload={"role": code},
            ip_address=_client_ip(request),
        )

    if to_add or to_remove:
        # Révoquer toutes les sessions de la cible → changement de droits immédiat
        await revoke_all_sessions(db, user.id)

    user.updated_at = _now()
    await db.commit()

    full_user = await _get_full_user_or_404(db, user_id)
    return UserOut.from_user(full_user)
