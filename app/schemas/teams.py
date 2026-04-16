from pydantic import BaseModel
from uuid import UUID
from datetime import datetime
from typing import Literal


class TeamCreate(BaseModel):
    name: str
    description: str | None = None


class TeamUpdate(BaseModel):
    name: str | None = None
    description: str | None = None


class TeamMemberAdd(BaseModel):
    user_id: UUID
    role: Literal["admin", "recruiter", "hiring_manager", "viewer"]


class TeamResponse(BaseModel):
    id: UUID
    company_id: UUID
    name: str
    description: str | None
    created_at: datetime

    class Config:
        from_attributes = True
