from pydantic import BaseModel, EmailStr, computed_field, field_validator
from typing import Optional, List, Dict, Any
from datetime import datetime
import uuid
from app.models.user import UserRole
from app.schemas.company import CompanyPublic


class ExperienceItem(BaseModel):
    """Single work experience entry"""
    title: str
    company: str
    start_date: str  # ISO format date string
    end_date: Optional[str] = None  # None for current position
    description: Optional[str] = None


class EducationItem(BaseModel):
    """Single education entry"""
    degree: str
    institution: str
    start_date: str  # ISO format date string
    end_date: Optional[str] = None  # None for ongoing
    description: Optional[str] = None


class UserBase(BaseModel):
    email: EmailStr
    full_name: Optional[str] = None
    headline: Optional[str] = None
    bio: Optional[str] = None
    phone: Optional[str] = None
    skills: Optional[List[str]] = None
    preferred_locations: Optional[List[str]] = None
    seniority: Optional[str] = None
    role: UserRole = UserRole.JOB_SEEKER


class UserCreate(UserBase):
    password: str


class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    headline: Optional[str] = None
    bio: Optional[str] = None
    phone: Optional[str] = None
    skills: Optional[List[str]] = None
    preferred_locations: Optional[List[str]] = None
    seniority: Optional[str] = None
    experience: Optional[List[Dict[str, Any]]] = None
    education: Optional[List[Dict[str, Any]]] = None

    @field_validator('full_name')
    @classmethod
    def full_name_must_not_be_empty_if_provided(cls, v):
        """If full_name is provided, it must not be empty or just whitespace"""
        if v is not None and (not v or not v.strip()):
            raise ValueError('Full name cannot be empty or just whitespace')
        return v.strip() if v else v


class UserInDB(UserBase):
    id: uuid.UUID
    company_id: Optional[uuid.UUID] = None
    experience: Optional[List[Dict[str, Any]]] = None
    education: Optional[List[Dict[str, Any]]] = None
    created_at: datetime
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True


class User(UserInDB):
    company: Optional[CompanyPublic] = None

    @computed_field
    @property
    def user_type(self) -> str:
        """Computed field to provide user_type for frontend compatibility"""
        if self.role in [UserRole.COMPANY_ADMIN, UserRole.COMPANY_RECRUITER]:
            return "company"
        return "job_seeker"


class UserProfile(User):
    """Extended user profile with additional stats"""
    application_count: Optional[int] = None
    swipe_count: Optional[int] = None