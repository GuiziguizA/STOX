import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditEventType, AuditLog


async def record_audit_event(
    db: AsyncSession,
    event_type: AuditEventType,
    *,
    actor_id: uuid.UUID | None = None,
    target_id: uuid.UUID | None = None,
    payload: dict[str, Any] | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> AuditLog:
    entry = AuditLog(
        actor_user_id=actor_id,
        target_user_id=target_id,
        event_type=event_type,
        payload_json=payload or {},
        ip_address=ip_address,
        user_agent=user_agent,
    )
    db.add(entry)
    await db.flush()
    return entry
