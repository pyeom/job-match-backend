from pydantic import BaseModel, EmailStr
from typing import Optional, List
from datetime import datetime
import uuid
from app.models.user import UserRole
from app.schemas.company import CompanyPublic


class UserBase(BaseModel):
    email: EmailStr
    full_name: Optional[str] = None
    headline: Optional[str] = None
    skills: Optional[List[str]] = None
    preferred_locations: Optional[List[str]] = None
    seniority: Optional[str] = None
    role: UserRole = UserRole.JOB_SEEKER


class UserCreate(UserBase):
    password: str


class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    headline: Optional[str] = None
    skills: Optional[List[str]] = None
    preferred_locations: Optional[List[str]] = None
    seniority: Optional[str] = None


class UserInDB(UserBase):
    id: uuid.UUID
    company_id: Optional[uuid.UUID] = None
    created_at: datetime
    updated_at: Optional[datetime]
    
    class Config:
        from_attributes = True


class User(UserInDB):
    company: Optional[CompanyPublic] = None
    

class UserProfile(User):
    """Extended user profile with additional stats"""
    application_count: Optional[int] = None
    swipe_count: Optional[int] = None