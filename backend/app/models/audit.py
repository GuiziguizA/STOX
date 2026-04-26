import enum
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Enum, ForeignKey, Text, text
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class AuditEventType(str, enum.Enum):
    user_register = "user.register"
    user_login = "user.login"
    user_login_failed = "user.login_failed"
    user_logout = "user.logout"
    user_logout_all = "user.logout_all"
    user_email_verified = "user.email_verified"
    user_password_reset_requested = "user.password_reset_requested"
    user_password_reset_completed = "user.password_reset_completed"
    user_password_changed = "user.password_changed"
    user_profile_updated = "user.profile_updated"
    user_suspended = "user.suspended"
    user_reactivated = "user.reactivated"
    user_deleted = "user.deleted"
    user_role_assigned = "user.role_assigned"
    user_role_revoked = "user.role_revoked"
    session_created = "session.created"
    session_revoked = "session.revoked"
    session_expired = "session.expired"


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    target_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    event_type: Mapped[AuditEventType] = mapped_column(
        Enum(AuditEventType, name="audit_event_type", create_type=False),
        nullable=False,
    )
    payload_json: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    ip_address: Mapped[str | None] = mapped_column(INET, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
