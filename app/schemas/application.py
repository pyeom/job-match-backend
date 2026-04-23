from pydantic import BaseModel, model_validator
from typing import Optional, List, Literal
from datetime import datetime
import uuid


# Stage and Status type definitions
# ApplicationStage is now dynamic — validated against the company's pipeline at runtime.
ApplicationStage = str
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
    stage_history: Optional[List[dict]] = None
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
    stage_info: Optional[dict] = None  # Stage metadata from company pipeline

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
    user_seniority: Optional[str] = None
    stage: ApplicationStage
    status: ApplicationStatus
    stage_updated_at: datetime
    rejection_reason: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    score: Optional[int] = None  # Match score (0-100)
    stage_info: Optional[dict] = None  # Stage metadata from company pipeline

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


# ---------------------------------------------------------------------------
# Blind-review schemas — TASK-041
# ---------------------------------------------------------------------------

class AnonymousCandidateInfo(BaseModel):
    """Candidate info shown to a company before identity reveal.

    All PII fields are absent.  Only professional-merit attributes are included
    so recruiters can evaluate the candidate solely on their skills and
    experience.
    """
    candidate_alias: str
    skills: Optional[List[str]] = None
    seniority: Optional[str] = None
    experience: Optional[List[dict]] = None
    education: Optional[List[dict]] = None

    class Config:
        from_attributes = True


class RevealedCandidateInfo(BaseModel):
    """Full candidate info available after a company explicitly reveals identity."""
    id: uuid.UUID
    full_name: Optional[str] = None
    email: str
    phone: Optional[str] = None
    avatar_url: Optional[str] = None
    linkedin_url: Optional[str] = None
    github_url: Optional[str] = None
    location: Optional[str] = None
    headline: Optional[str] = None
    skills: Optional[List[str]] = None
    seniority: Optional[str] = None
    experience: Optional[List[dict]] = None
    education: Optional[List[dict]] = None

    class Config:
        from_attributes = True


class ApplicationAnonymousSchema(BaseModel):
    """Company-facing application response with candidate identity redacted.

    Returned by the list/detail endpoints when the application has NOT yet
    been revealed.  The ``candidate`` field contains only professional
    attributes plus a stable alias.
    """
    id: uuid.UUID
    job_id: uuid.UUID
    job_title: str
    stage: ApplicationStage
    status: ApplicationStatus
    stage_updated_at: datetime
    rejection_reason: Optional[str] = None
    cover_letter: Optional[str] = None
    score: Optional[int] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    is_revealed: bool = False
    candidate: AnonymousCandidateInfo
    stage_info: Optional[dict] = None  # Stage metadata from company pipeline

    class Config:
        from_attributes = True


class RevealRecord(BaseModel):
    """Minimal information about when/who performed the reveal."""
    revealed_by_user_id: uuid.UUID
    revealed_at: datetime
    stage_at_reveal: str

    class Config:
        from_attributes = True


class ApplicationRevealedSchema(BaseModel):
    """Company-facing application response with full candidate identity.

    Returned by the list/detail endpoints when the application HAS been
    revealed, and directly by the POST .../reveal endpoint.
    """
    id: uuid.UUID
    job_id: uuid.UUID
    job_title: str
    stage: ApplicationStage
    status: ApplicationStatus
    stage_updated_at: datetime
    rejection_reason: Optional[str] = None
    cover_letter: Optional[str] = None
    score: Optional[int] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    is_revealed: bool = True
    reveal_info: Optional[RevealRecord] = None
    candidate: RevealedCandidateInfo
    stage_info: Optional[dict] = None  # Stage metadata from company pipeline

    class Config:
        from_attributes = True