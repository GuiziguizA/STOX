"""Routes roles & permissions — lecture seule MVP"""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.db import get_db
from app.core.deps import get_current_user, require_permission
from app.models.user import Permission, Role, User
from app.schemas.user import PermissionOut, RoleOut

router = APIRouter(tags=["roles"])


# ── GET /roles ────────────────────────────────────────────────────────────────

@router.get("/roles", response_model=list[RoleOut])
async def list_roles(
    db: Annotated[AsyncSession, Depends(get_db)],
    actor: Annotated[User, Depends(get_current_user)],
):
    """Accessible avec roles.manage OU users.read."""
    from app.core.deps import _get_user_permissions
    perms = _get_user_permissions(actor)
    if "roles.manage" not in perms and "users.read" not in perms:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission 'roles.manage' ou 'users.read' requise",
        )

    result = await db.execute(
        select(Role).options(
            selectinload(Role.role_permissions).selectinload("permission")
        ).order_by(Role.label)
    )
    roles = result.scalars().all()
    return [RoleOut.from_orm_role(r) for r in roles]


# ── GET /permissions ──────────────────────────────────────────────────────────

@router.get("/permissions", response_model=list[PermissionOut])
async def list_permissions(
    db: Annotated[AsyncSession, Depends(get_db)],
    _actor: Annotated[User, Depends(require_permission("roles.manage"))],
):
    result = await db.execute(select(Permission).order_by(Permission.code))
    perms = result.scalars().all()
    return [PermissionOut.model_validate(p) for p in perms]
