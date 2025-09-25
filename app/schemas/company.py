from pydantic import BaseModel
from typing import Optional, List, Dict, Generic, TypeVar
from datetime import datetime
import uuid

T = TypeVar('T')


class CompanyBase(BaseModel):
    name: str
    description: Optional[str] = None
    website: Optional[str] = None
    industry: Optional[str] = None
    size: Optional[str] = None
    location: Optional[str] = None


class CompanyCreate(CompanyBase):
    pass


class CompanyUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    website: Optional[str] = None
    industry: Optional[str] = None
    size: Optional[str] = None
    location: Optional[str] = None
    is_active: Optional[bool] = None


class CompanyInDB(CompanyBase):
    id: uuid.UUID
    is_verified: bool
    is_active: bool
    created_at: datetime
    updated_at: Optional[datetime]
    
    class Config:
        from_attributes = True


class Company(CompanyInDB):
    job_count: Optional[int] = None  # For company profile with job statistics
    user_count: Optional[int] = None  # For company profile with user statistics


class CompanyPublic(BaseModel):
    """Public company information for job seekers"""
    id: uuid.UUID
    name: str
    description: Optional[str] = None
    website: Optional[str] = None
    logo_url: Optional[str] = None
    industry: Optional[str] = None
    size: Optional[str] = None
    location: Optional[str] = None
    founded_year: Optional[int] = None
    is_verified: bool
    
    class Config:
        from_attributes = True


class ConversionMetrics(BaseModel):
    """Application conversion metrics"""
    total_applications: int
    reviewed_applications: int
    hired_applications: int
    rejected_applications: int
    conversion_rate_to_review: float  # % of applications that get reviewed
    conversion_rate_to_hire: float    # % of applications that result in hire


class ApplicationStatusBreakdown(BaseModel):
    """Breakdown of applications by status"""
    submitted: int
    waiting_for_review: int
    hr_meeting: int
    technical_interview: int
    final_interview: int
    hired: int
    rejected: int


class RecentActivity(BaseModel):
    """Recent activity summary"""
    applications_last_7_days: int
    applications_last_30_days: int
    new_jobs_last_7_days: int
    new_jobs_last_30_days: int


class TopPerformingJob(BaseModel):
    """Top performing job information"""
    job_id: uuid.UUID
    job_title: str
    application_count: int
    conversion_rate: float
    created_at: datetime


class CompanyStats(BaseModel):
    """Comprehensive company statistics for dashboard"""
    total_active_jobs: int
    total_applications: int
    conversion_metrics: ConversionMetrics
    recent_activity: RecentActivity
    top_performing_jobs: List[TopPerformingJob]
    application_status_breakdown: ApplicationStatusBreakdown
    
    # Additional dashboard metrics
    avg_applications_per_job: float
    most_popular_seniority_level: Optional[str]
    most_popular_job_location: Optional[str]


class TeamMemberInfo(BaseModel):
    """Company team member information"""
    id: uuid.UUID
    email: str
    full_name: Optional[str] = None
    role: str  # COMPANY_RECRUITER, COMPANY_ADMIN
    phone: Optional[str] = None
    created_at: datetime
    
    class Config:
        from_attributes = True


class TeamMemberInvite(BaseModel):
    """Team member invitation request"""
    email: str
    role: str  # COMPANY_RECRUITER or COMPANY_ADMIN
    full_name: Optional[str] = None


class TeamMemberRoleUpdate(BaseModel):
    """Team member role update request"""
    role: str  # COMPANY_RECRUITER or COMPANY_ADMIN


class CompanyDashboardStats(BaseModel):
    """Simple dashboard stats for frontend compatibility"""
    total_jobs: int
    active_jobs: int
    total_applications: int
    pending_applications: int
    accepted_applications: int
    rejected_applications: int


class PaginatedResponse(BaseModel, Generic[T]):
    """Generic paginated response"""
    items: List[T]
    total: int
    page: Optional[int] = None
    limit: Optional[int] = None