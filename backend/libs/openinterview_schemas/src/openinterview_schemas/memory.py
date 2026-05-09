from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class LongTermMemoryOut(BaseModel):
    id: UUID
    user_id: UUID
    project_id: UUID | None = None
    kind: str
    content: str
    weight: float
    pinned: bool = False
    meta: dict | None = None
    source_session_id: UUID | None = None
    created_at: datetime


class LongTermMemoryUpdate(BaseModel):
    pinned: bool | None = None
    project_id: UUID | None = None
