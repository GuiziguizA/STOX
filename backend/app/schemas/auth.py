import uuid
from datetime import datetime

from pydantic import BaseModel


class SessionOut(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    user_id: uuid.UUID
    expires_at: datetime
    idle_expires_at: datetime
    last_seen_at: datetime
    ip_address: str | None = None
    created_at: datetime
