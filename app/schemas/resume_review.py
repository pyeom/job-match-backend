"""
Pydantic schemas for AI-powered resume review.
"""
from pydantic import BaseModel, Field
from typing import List, Optional
from uuid import UUID


class ResumeReviewRequest(BaseModel):
    """Request schema for resume review."""
    document_id: UUID = Field(..., description="UUID of the uploaded resume document")
    target_job_id: Optional[UUID] = Field(None, description="Optional: UUID of specific job to analyze against")


class ResumeSection(BaseModel):
    """Individual section analysis in the resume."""
    section_name: str = Field(..., description="Name of the resume section")
    score: float = Field(..., ge=0, le=1, description="Section quality score (0-1)")
    strengths: List[str] = Field(default_factory=list, description="Strengths found in this section")
    weaknesses: List[str] = Field(default_factory=list, description="Weaknesses or areas for improvement")
    suggestions: List[str] = Field(default_factory=list, description="Specific improvement suggestions")


class KeywordAnalysis(BaseModel):
    """Keyword analysis results."""
    matched_keywords: List[str] = Field(default_factory=list, description="Keywords present in resume")
    missing_keywords: List[str] = Field(default_factory=list, description="Important keywords missing from resume")
    keyword_density_score: float = Field(..., ge=0, le=1, description="Overall keyword coverage score (0-1)")


class ResumeReviewResponse(BaseModel):
    """Response schema for resume review results."""
    document_id: UUID = Field(..., description="UUID of the reviewed document")
    target_job_id: Optional[UUID] = Field(None, description="UUID of target job if specified")

    # Overall scores
    overall_score: float = Field(..., ge=0, le=100, description="Overall resume quality score (0-100)")
    structure_score: float = Field(..., ge=0, le=1, description="Resume structure quality (0-1)")
    content_score: float = Field(..., ge=0, le=1, description="Content quality score (0-1)")
    formatting_score: float = Field(..., ge=0, le=1, description="Formatting and readability score (0-1)")
    relevance_score: Optional[float] = Field(None, ge=0, le=1, description="Relevance to target job if specified (0-1)")

    # Executive summary
    summary: str = Field(..., description="High-level summary of resume strengths and areas for improvement")

    # Section-by-section analysis
    sections: List[ResumeSection] = Field(default_factory=list, description="Detailed section-by-section analysis")

    # Keyword analysis
    keyword_analysis: Optional[KeywordAnalysis] = Field(None, description="Keyword analysis against target job")

    # Top-level suggestions
    top_suggestions: List[str] = Field(default_factory=list, description="Top 5-7 most impactful suggestions")

    # Detailed findings
    strengths: List[str] = Field(default_factory=list, description="Overall resume strengths")
    weaknesses: List[str] = Field(default_factory=list, description="Overall areas for improvement")

    # Metadata
    word_count: int = Field(..., description="Total word count in resume")
    has_contact_info: bool = Field(..., description="Whether resume contains contact information")
    has_quantified_achievements: bool = Field(..., description="Whether resume contains measurable achievements")

    class Config:
        from_attributes = True
