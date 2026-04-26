import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, field_validator

from app.models.user import UserStatus


class PermissionOut(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    code: str
    label: str
    description: str | None = None


class RoleOut(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    code: str
    label: str
    description: str | None = None
    permissions: list[PermissionOut] = []

    @classmethod
    def from_orm_role(cls, role: object) -> "RoleOut":
        perms = [
            PermissionOut.model_validate(rp.permission)
            for rp in getattr(role, "role_permissions", [])
        ]
        return cls(
            id=getattr(role, "id"),
            code=getattr(role, "code"),
            label=getattr(role, "label"),
            description=getattr(role, "description"),
            permissions=perms,
        )


class ProfileOut(BaseModel):
    model_config = {"from_attributes": True}

    first_name: str | None = None
    last_name: str | None = None
    avatar_url: str | None = None
    locale: str
    timezone: str


class UserOut(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    email: str
    status: UserStatus
    email_verified_at: datetime | None = None
    last_login_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    profile: ProfileOut | None = None
    roles: list[RoleOut] = []
    permissions: list[str] = []

    @classmethod
    def from_user(cls, user: object) -> "UserOut":
        roles = [
            RoleOut.from_orm_role(ur.role)
            for ur in getattr(user, "user_roles", [])
        ]
        perms = {
            rp.permission.code
            for ur in getattr(user, "user_roles", [])
            for rp in ur.role.role_permissions
        }
        return cls(
            id=getattr(user, "id"),
            email=getattr(user, "email"),
            status=getattr(user, "status"),
            email_verified_at=getattr(user, "email_verified_at"),
            last_login_at=getattr(user, "last_login_at"),
            created_at=getattr(user, "created_at"),
            updated_at=getattr(user, "updated_at"),
            profile=ProfileOut.model_validate(getattr(user, "profile")) if getattr(user, "profile") else None,
            roles=roles,
            permissions=sorted(perms),
        )


class ProfileUpdateIn(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    locale: str | None = None
    timezone: str | None = None


class UserUpdateIn(BaseModel):
    email: EmailStr | None = None
    profile: ProfileUpdateIn | None = None


class UserStatusUpdateIn(BaseModel):
    status: UserStatus

    @field_validator("status")
    @classmethod
    def no_pending_via_patch(cls, v: UserStatus) -> UserStatus:
        if v == UserStatus.pending:
            raise ValueError("Le statut 'pending' n'est pas assignable manuellement")
        return v


class UserRolesUpdateIn(BaseModel):
    role_codes: list[str]


class UserInviteIn(BaseModel):
    email: EmailStr
    first_name: str | None = None
    last_name: str | None = None
    role_codes: list[str] = []
