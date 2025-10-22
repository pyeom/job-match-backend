from pydantic import BaseModel, model_validator
from typing import Optional, List, Literal
from datetime import datetime
import uuid


# Stage and Status type definitions
ApplicationStage = Literal['SUBMITTED', 'REVIEW', 'INTERVIEW', 'TECHNICAL', 'DECISION']
ApplicationStatus = Literal['ACTIVE', 'HIRED', 'REJECTED']


class ApplicationCreate(BaseModel):
    job_id: uuid.UUID
    cover_letter: Optional[str] = None


class ApplicationUpdate(BaseModel):
    """Update application stage and/or status"""
    stage: Optional[ApplicationStage] = None
    status: Optional[ApplicationStatus] = None
    rejection_reason: Optional[str] = None
    notes: Optional[str] = None

    @model_validator(mode='after')
    def validate_rejection_reason(self):
        if self.status == 'REJECTED' and not self.rejection_reason:
            raise ValueError('rejection_reason is required when status is REJECTED')
        return self


class BulkApplicationUpdate(BaseModel):
    application_ids: List[uuid.UUID]
    status: str
    notes: Optional[str] = None


class UserBasicInfo(BaseModel):
    """Basic user information for application listings"""
    id: uuid.UUID
    email: str
    full_name: Optional[str] = None
    skills: Optional[List[str]] = None
    seniority: Optional[str] = None
    location: Optional[str] = None  # Primary preferred location
    
    class Config:
        from_attributes = True


class JobBasicInfo(BaseModel):
    """Basic job information for application listings"""
    id: uuid.UUID
    title: str
    location: Optional[str] = None
    seniority: Optional[str] = None
    
    class Config:
        from_attributes = True


class Application(BaseModel):
    """Base application schema"""
    id: uuid.UUID
    user_id: uuid.UUID
    job_id: uuid.UUID
    stage: ApplicationStage
    status: ApplicationStatus
    stage_updated_at: datetime
    rejection_reason: Optional[str]
    cover_letter: Optional[str]
    notes: Optional[str]
    created_at: datetime
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True


class ApplicationWithDetails(Application):
    """Application with user and job details for company dashboard and job seeker view"""
    user: Optional[UserBasicInfo] = None
    job: Optional["JobDetails"] = None

    class Config:
        from_attributes = True


class CompanyDetails(BaseModel):
    """Company details for application responses"""
    id: uuid.UUID
    name: str
    logo_url: Optional[str] = None
    location: Optional[str] = None
    size: Optional[str] = None
    industry: Optional[str] = None

    class Config:
        from_attributes = True


class JobDetails(BaseModel):
    """Job details for application responses"""
    id: uuid.UUID
    title: str
    location: Optional[str] = None
    seniority: Optional[str] = None
    short_description: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[List[str]] = None
    salary_min: Optional[int] = None
    salary_max: Optional[int] = None
    remote: Optional[bool] = None
    created_at: datetime
    company: Optional[CompanyDetails] = None

    class Config:
        from_attributes = True


class ApplicationStatusFilter(BaseModel):
    """Filter for application status queries"""
    statuses: Optional[List[str]] = None
    created_after: Optional[datetime] = None
    created_before: Optional[datetime] = None
    seniority_levels: Optional[List[str]] = None
    locations: Optional[List[str]] = None


class ApplicationWithUserResponse(BaseModel):
    """Flattened application response with stage and status"""
    id: uuid.UUID
    job_id: uuid.UUID
    job_title: str
    user_id: uuid.UUID
    user_email: str
    user_full_name: Optional[str] = None
    user_headline: Optional[str] = None
    user_skills: Optional[List[str]] = None
    stage: ApplicationStage
    status: ApplicationStatus
    stage_updated_at: datetime
    rejection_reason: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ApplicationExport(BaseModel):
    """Application data for export"""
    application_id: uuid.UUID
    user_email: str
    user_name: Optional[str]
    job_title: str
    status: str
    applied_date: datetime
    last_updated: Optional[datetime]
    cover_letter: Optional[str]
    notes: Optional[str]