from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from enum import Enum
import uuid


class SortField(str, Enum):
    MATCH_SCORE = "match_score"
    POSTED_DATE = "posted_date"
    SALARY = "salary"


class SortOrder(str, Enum):
    ASC = "asc"
    DESC = "desc"


class WorkArrangement(str, Enum):
    REMOTE = "Remote"
    HYBRID = "Hybrid"
    ONSITE = "On-site"


class SeniorityLevel(str, Enum):
    ENTRY = "Entry"
    JUNIOR = "Junior"
    MID = "Mid"
    SENIOR = "Senior"
    LEAD = "Lead"
    EXECUTIVE = "Executive"


class JobType(str, Enum):
    FULL_TIME = "Full-time"
    PART_TIME = "Part-time"
    CONTRACT = "Contract"
    FREELANCE = "Freelance"
    INTERNSHIP = "Internship"


class JobSearchRequest(BaseModel):
    """Request model for job search with filters"""
    keyword: Optional[str] = Field(None, description="Search job title, company name, description")
    salary_min: Optional[int] = Field(None, ge=0, description="Minimum salary filter")
    salary_max: Optional[int] = Field(None, ge=0, description="Maximum salary filter")
    currency: Optional[str] = Field(None, max_length=3, description="Currency filter (USD, EUR, etc.)")
    salary_negotiable: Optional[bool] = Field(None, description="Filter for negotiable salary jobs")
    locations: Optional[List[str]] = Field(None, description="Multi-select location filter")
    radius_km: Optional[int] = Field(None, description="Location radius in km (10, 25, 50, 100)")
    latitude: Optional[float] = Field(None, ge=-90, le=90, description="User latitude for radius search")
    longitude: Optional[float] = Field(None, ge=-180, le=180, description="User longitude for radius search")
    work_arrangement: Optional[List[WorkArrangement]] = Field(None, description="Remote/Hybrid/On-site")
    seniority_levels: Optional[List[SeniorityLevel]] = Field(None, description="Seniority levels filter")
    job_types: Optional[List[JobType]] = Field(None, description="Job types filter")
    skills: Optional[List[str]] = Field(None, description="Skills/tags filter")
    sort_by: Optional[SortField] = Field(SortField.MATCH_SCORE, description="Sort field")
    sort_order: Optional[SortOrder] = Field(SortOrder.DESC, description="Sort order")
    skip: int = Field(0, ge=0, description="Pagination offset")
    limit: int = Field(20, ge=1, le=100, description="Pagination limit")


class JobSearchResponse(BaseModel):
    """Response model for job search"""
    items: List[dict]  # Will contain JobWithCompany instances
    total: int
    skip: int
    limit: int


class FilterPresetBase(BaseModel):
    """Base model for filter presets"""
    name: str = Field(..., min_length=1, max_length=100)
    filters: dict = Field(..., description="Filter parameters as JSON")
    is_default: bool = Field(False, description="Whether this is the default preset")


class FilterPresetCreate(FilterPresetBase):
    """Create filter preset request"""
    pass


class FilterPresetUpdate(BaseModel):
    """Update filter preset request"""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    filters: Optional[dict] = None
    is_default: Optional[bool] = None


class FilterPreset(FilterPresetBase):
    """Filter preset response"""
    id: uuid.UUID
    user_id: uuid.UUID
    created_at: datetime
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True


class RecentSearchBase(BaseModel):
    """Base model for recent searches"""
    query: Optional[str] = Field(None, max_length=255, description="Keyword search query")
    filters_used: Optional[dict] = Field(None, description="Filters applied in the search")


class RecentSearchCreate(RecentSearchBase):
    """Create recent search request"""
    pass


class RecentSearch(RecentSearchBase):
    """Recent search response"""
    id: uuid.UUID
    user_id: uuid.UUID
    searched_at: datetime

    class Config:
        from_attributes = True
