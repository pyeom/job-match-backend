from pydantic import BaseModel, EmailStr, validator, field_validator
from typing import Optional, Union
import uuid
from app.models.user import UserRole


class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class TokenData(BaseModel):
    user_id: Optional[str] = None


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserCreate(BaseModel):
    email: EmailStr
    password: str
    full_name: str
    role: UserRole = UserRole.JOB_SEEKER

    @field_validator('full_name')
    @classmethod
    def full_name_must_not_be_empty(cls, v):
        if not v or not v.strip():
            raise ValueError('Full name is required and cannot be empty')
        return v.strip()


class CompanyUserCreate(BaseModel):
    """
    Schema for creating company users with role validation and mapping.

    Role Mapping:
    - 'admin' → COMPANY_ADMIN: Full access to company settings, jobs, and team management
    - 'recruiter' → COMPANY_RECRUITER: Can post jobs, review applications, manage hiring
    - 'hr' → COMPANY_RECRUITER: HR representatives get recruiter-level permissions
    """
    email: EmailStr
    password: str
    full_name: str
    role: Union[UserRole, str]  # Accept both enum and string values from frontend
    company_name: str
    company_description: Optional[str] = None
    company_website: Optional[str] = None
    company_industry: Optional[str] = None
    company_size: Optional[str] = None
    company_location: Optional[str] = None

    @field_validator('full_name')
    @classmethod
    def full_name_must_not_be_empty(cls, v):
        if not v or not v.strip():
            raise ValueError('Full name is required and cannot be empty')
        return v.strip()

    @validator('role')
    def role_must_be_company_role(cls, v):
        """
        Validate and map role values from frontend to backend UserRole enum.
        Accepts both string values from frontend and UserRole enum values.
        """
        role_mapping = {
            # Frontend string values → Backend enum values
            'admin': UserRole.COMPANY_ADMIN,
            'recruiter': UserRole.COMPANY_RECRUITER,
            'hr': UserRole.COMPANY_RECRUITER,  # HR users get recruiter permissions
            # Backend enum values (passthrough)
            UserRole.COMPANY_ADMIN: UserRole.COMPANY_ADMIN,
            UserRole.COMPANY_RECRUITER: UserRole.COMPANY_RECRUITER,
        }
        
        if v in role_mapping:
            return role_mapping[v]
        
        valid_roles = ['admin', 'recruiter', 'hr']
        raise ValueError(f'Company users must have one of these roles: {", ".join(valid_roles)}. Got: {v}')


class CompanyCreate(BaseModel):
    name: str
    description: Optional[str] = None
    website: Optional[str] = None
    industry: Optional[str] = None
    size: Optional[str] = None
    location: Optional[str] = None


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class TokenRefreshResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class LogoutResponse(BaseModel):
    message: str
    detail: Optional[str] = None