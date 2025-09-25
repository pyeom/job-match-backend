from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
import uuid
from app.schemas.company import CompanyPublic


class JobBase(BaseModel):
    title: str
    location: Optional[str] = None
    short_description: Optional[str] = None  # Brief description for job cards
    description: Optional[str] = None  # Full description for detailed views
    tags: Optional[List[str]] = None
    seniority: Optional[str] = None
    salary_min: Optional[int] = None
    salary_max: Optional[int] = None
    remote: Optional[bool] = False


class JobCreate(JobBase):
    pass


class JobUpdate(BaseModel):
    title: Optional[str] = None
    location: Optional[str] = None
    short_description: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[List[str]] = None
    seniority: Optional[str] = None
    salary_min: Optional[int] = None
    salary_max: Optional[int] = None
    remote: Optional[bool] = None
    is_active: Optional[bool] = None


class JobInDB(JobBase):
    id: uuid.UUID
    company_id: uuid.UUID
    is_active: bool
    created_at: datetime
    updated_at: Optional[datetime]
    
    class Config:
        from_attributes = True


class Job(JobInDB):
    company: Optional[CompanyPublic] = None
    score: Optional[int] = None  # For discover endpoint with ML scoring


class JobWithCompany(Job):
    """Job with full company information loaded"""
    pass


class JobPerformanceMetrics(BaseModel):
    """Job performance metrics for company dashboard"""
    total_applications: int
    applications_last_7_days: int
    applications_last_30_days: int
    conversion_rate_to_review: float
    conversion_rate_to_hire: float
    avg_time_to_review: Optional[float] = None  # Days
    avg_time_to_hire: Optional[float] = None    # Days
    most_common_applicant_seniority: Optional[str] = None
    rejection_rate: float


class JobWithMetrics(Job):
    """Job with performance metrics for company dashboard"""
    metrics: Optional[JobPerformanceMetrics] = None


class JobStatusUpdate(BaseModel):
    """Job status update request"""
    is_active: bool


class JobBulkStatusUpdate(BaseModel):
    """Bulk job status update request"""
    job_ids: List[uuid.UUID]
    is_active: bool


class DiscoverResponse(BaseModel):
    """Response model for the discover endpoint with cursor-based pagination"""
    items: List[JobWithCompany]
    next_cursor: Optional[str] = None