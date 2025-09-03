from pydantic import BaseModel
from typing import Optional
from datetime import datetime
import uuid


class ApplicationCreate(BaseModel):
    job_id: uuid.UUID
    cover_letter: Optional[str] = None


class ApplicationUpdate(BaseModel):
    status: Optional[str] = None  # SUBMITTED, REJECTED, ACCEPTED
    notes: Optional[str] = None


class Application(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    job_id: uuid.UUID
    status: str
    cover_letter: Optional[str]
    notes: Optional[str]
    created_at: datetime
    updated_at: Optional[datetime]
    
    class Config:
        orm_mode = True