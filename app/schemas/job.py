from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
import uuid


class JobBase(BaseModel):
    title: str
    company: str
    location: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[List[str]] = None
    seniority: Optional[str] = None
    salary_min: Optional[int] = None
    salary_max: Optional[int] = None
    remote: Optional[bool] = False


class JobCreate(JobBase):
    pass


class JobUpdate(BaseModel):
    title: Optional[str] = None
    company: Optional[str] = None
    location: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[List[str]] = None
    seniority: Optional[str] = None
    salary_min: Optional[int] = None
    salary_max: Optional[int] = None
    remote: Optional[bool] = None
    is_active: Optional[bool] = None


class JobInDB(JobBase):
    id: uuid.UUID
    is_active: bool
    created_at: datetime
    updated_at: Optional[datetime]
    
    class Config:
        orm_mode = True


class Job(JobInDB):
    score: Optional[int] = None  # For discover endpoint with ML scoring