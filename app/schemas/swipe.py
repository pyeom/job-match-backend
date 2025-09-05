from pydantic import BaseModel
from datetime import datetime
import uuid


class SwipeCreate(BaseModel):
    job_id: uuid.UUID
    direction: str  # LEFT or RIGHT


class Swipe(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    job_id: uuid.UUID
    direction: str
    created_at: datetime
    
    class Config:
        from_attributes = True