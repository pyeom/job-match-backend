"""
Resume Parser Schemas - Pydantic models for AI-powered resume parsing.
"""

from typing import List, Optional
from uuid import UUID
from pydantic import BaseModel, Field


class ParsedContact(BaseModel):
    """Parsed contact information from resume."""
    email: Optional[str] = None
    phone: Optional[str] = None
    full_name: Optional[str] = None
    location: Optional[str] = None
    linkedin: Optional[str] = None
    github: Optional[str] = None
    portfolio: Optional[str] = None


class ParsedSummary(BaseModel):
    """Parsed summary/objective section."""
    summary: Optional[str] = None
    headline: Optional[str] = None


class ParsedExperience(BaseModel):
    """Parsed work experience entry."""
    title: str
    company: str
    start_date: Optional[str] = None  # Format: "YYYY-MM" or "Month YYYY"
    end_date: Optional[str] = None  # None means "Present"
    description: Optional[str] = None
    location: Optional[str] = None
    is_current: bool = False


class ParsedEducation(BaseModel):
    """Parsed education entry."""
    degree: str
    institution: str
    field_of_study: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    gpa: Optional[str] = None
    description: Optional[str] = None


class ParsedSkills(BaseModel):
    """Parsed skills categorized by type."""
    technical_skills: List[str] = Field(default_factory=list)
    soft_skills: List[str] = Field(default_factory=list)
    languages: List[str] = Field(default_factory=list)
    certifications: List[str] = Field(default_factory=list)
    all_skills: List[str] = Field(default_factory=list)


class ResumeParseResponse(BaseModel):
    """Complete parsed resume response."""
    contact: ParsedContact = Field(default_factory=ParsedContact)
    summary: ParsedSummary = Field(default_factory=ParsedSummary)
    experience: List[ParsedExperience] = Field(default_factory=list)
    education: List[ParsedEducation] = Field(default_factory=list)
    skills: ParsedSkills = Field(default_factory=ParsedSkills)
    raw_text: Optional[str] = None
    confidence_score: float = Field(default=0.0, ge=0.0, le=1.0)
    parsing_method: str = "hybrid"
    sections_found: List[str] = Field(default_factory=list)


class ResumeParseRequest(BaseModel):
    """Request to parse a resume document."""
    document_id: UUID = Field(..., description="UUID of the uploaded resume document")
    auto_fill_profile: bool = Field(
        default=True,
        description="Whether to automatically update profile with parsed data"
    )


class ProfileAutoFillResponse(BaseModel):
    """Response after parsing and optionally auto-filling profile."""
    document_id: UUID
    parsed_data: ResumeParseResponse
    profile_updated: bool = False
    fields_updated: List[str] = Field(default_factory=list)
    message: str = ""
