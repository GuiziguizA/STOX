import uuid
from datetime import datetime
from ipaddress import IPv4Address, IPv6Address
from typing import Any

from pydantic import BaseModel, EmailStr, field_validator


class SessionOut(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    user_id: uuid.UUID
    expires_at: datetime
    idle_expires_at: datetime
    last_seen_at: datetime
    ip_address: str | None = None
    user_agent: str | None = None
    created_at: datetime

    @field_validator("ip_address", mode="before")
    @classmethod
    def _coerce_ip(cls, value: Any) -> str | None:
        # PostgreSQL INET column → asyncpg renvoie un IPv4Address/IPv6Address ;
        # Pydantic v2 strict ne coerce plus implicitement, on convertit en str.
        if value is None:
            return None
        if isinstance(value, (IPv4Address, IPv6Address)):
            return str(value)
        return value


class RegisterIn(BaseModel):
    email: EmailStr
    password: str
    first_name: str | None = None
    last_name: str | None = None

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Le mot de passe doit faire au moins 8 caractères")
        return v


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class VerifyEmailIn(BaseModel):
    token: str


class ResendVerificationIn(BaseModel):
    pass


class ForgotPasswordIn(BaseModel):
    email: EmailStr


class ResetPasswordIn(BaseModel):
    token: str
    password: str

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Le mot de passe doit faire au moins 8 caractères")
        return v


class PasswordChangeIn(BaseModel):
    current_password: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def new_password_strength(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Le nouveau mot de passe doit faire au moins 8 caractères")
        return v
