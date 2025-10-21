"""
Statistics and analytics schemas.

This module contains Pydantic schemas for various statistics, metrics,
and analytics endpoints related to jobs, applications, and company data.
"""

from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
import uuid


class JobApplicationStats(BaseModel):
    """Application statistics for a specific job"""
    job_id: uuid.UUID
    job_title: str
    total_applications: int
    pending_applications: int
    in_review_applications: int
    hired_applications: int
    rejected_applications: int
    created_at: datetime

    class Config:
        from_attributes = True


class CompanyApplicationMetrics(BaseModel):
    """Overall application metrics for the company"""
    total_applications: int
    applications_last_30_days: int
    applications_last_7_days: int
    avg_applications_per_job: float
    most_applied_job: Optional[JobApplicationStats] = None
    conversion_rate: float  # hired / total applications
    jobs_with_applications: List[JobApplicationStats]


class JobApplicationCount(BaseModel):
    """Simple job application count for dashboard widgets"""
    job_id: uuid.UUID
    job_title: str
    application_count: int
    is_active: bool

    class Config:
        from_attributes = True


class ApplicationCounts(BaseModel):
    """Application counts by status for a job"""
    total: int = Field(description="Total number of applications")
    pending: int = Field(description="Applications in progress (submitted through final interview)")
    accepted: int = Field(description="Accepted applications (hired)")
    rejected: int = Field(description="Rejected applications")


class RecentApplicant(BaseModel):
    """Basic information about recent applicant"""
    user_full_name: Optional[str] = None
    user_email: str
    applied_at: datetime
    status: str  # Frontend status: SUBMITTED, ACCEPTED, REJECTED

    class Config:
        from_attributes = True


class JobWithApplications(BaseModel):
    """
    Job information with application counts and recent applicants.

    This schema is used for the jobs-with-applications endpoint that provides
    a comprehensive view of each job's application status.
    """
    id: uuid.UUID
    title: str
    created_at: datetime
    status: str  # "active" or "inactive"
    application_counts: ApplicationCounts
    recent_applicants: List[RecentApplicant]

    class Config:
        from_attributes = True


class JobsWithApplicationsResponse(BaseModel):
    """
    Response for jobs-with-applications endpoint (legacy).

    This schema maintains backward compatibility with existing endpoints.
    """
    jobs: List[JobWithApplications]
    total_applications: int
    total_jobs: int


class PaginationMeta(BaseModel):
    """Pagination metadata"""
    page: int = Field(description="Current page number (1-indexed)")
    limit: int = Field(description="Items per page")
    total: int = Field(description="Total number of items")
    total_pages: int = Field(description="Total number of pages")


class JobOverview(BaseModel):
    """
    Job overview with statistics for jobs overview endpoint.

    This is the new schema for the refactored /jobs/overview endpoint.
    """
    id: uuid.UUID
    title: str
    created_at: datetime
    status: str  # "active" or "inactive"
    application_counts: ApplicationCounts
    recent_applicants: List[RecentApplicant]

    class Config:
        from_attributes = True


class JobsOverviewSummary(BaseModel):
    """Summary statistics for jobs overview"""
    total_jobs: int = Field(description="Total number of jobs in the result set")
    total_applications: int = Field(description="Total applications across all jobs")


class JobsOverviewResponse(BaseModel):
    """
    Response for the new /jobs/overview endpoint.

    Provides paginated jobs with application statistics and summary metrics.
    """
    jobs: List[JobOverview]
    pagination: PaginationMeta
    summary: JobsOverviewSummary


class ApplicantsRecentResponse(BaseModel):
    """Response for recent applicants endpoint"""
    job_id: uuid.UUID
    job_title: str
    recent_applicants: List[RecentApplicant]


class DashboardStatsResponse(BaseModel):
    """
    Dashboard statistics response.

    Provides high-level metrics for company dashboard.
    """
    total_jobs: int
    active_jobs: int
    total_applications: int
    applications_last_30_days: int
    applications_last_7_days: int
    conversion_rate: float = Field(description="Conversion rate (0.0-1.0)")

    class Config:
        from_attributes = True


class JobApplicationStatDetail(BaseModel):
    """
    Detailed job application statistics.

    Used for analytics endpoints that provide granular breakdowns.
    """
    job_id: uuid.UUID
    job_title: str
    is_active: bool
    total_applications: int
    pending_applications: int
    accepted_applications: int
    rejected_applications: int
    created_at: datetime

    class Config:
        from_attributes = True


class JobApplicationStatsResponse(BaseModel):
    """Response for job application statistics endpoint"""
    jobs: List[JobApplicationStatDetail]
    total_jobs: int
    total_applications: int
