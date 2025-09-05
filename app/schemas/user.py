from pydantic import BaseModel, EmailStr
from typing import Optional, List
from datetime import datetime
import uuid


class UserBase(BaseModel):
    email: EmailStr
    full_name: Optional[str] = None
    headline: Optional[str] = None
    skills: Optional[List[str]] = None
    preferred_locations: Optional[List[str]] = None
    seniority: Optional[str] = None


class UserCreate(UserBase):
    password: str


class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    headline: Optional[str] = None
    skills: Optional[List[str]] = None
    preferred_locations: Optional[List[str]] = None
    seniority: Optional[str] = None


class User(UserBase):
    id: uuid.UUID
    created_at: datetime
    updated_at: Optional[datetime]
    
    class Config:
        from_attributes = True