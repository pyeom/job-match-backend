from pydantic import BaseModel, Field
from typing import Optional
import uuid


class MatchFactorExplanation(BaseModel):
    """Detailed explanation for a single match factor"""
    score: float = Field(..., ge=0.0, le=1.0, description="Normalized score (0-1) for this factor")
    weight: float = Field(..., ge=0.0, le=1.0, description="Weight of this factor in the overall score")
    weighted_contribution: float = Field(..., ge=0.0, le=1.0, description="Contribution to final score (score * weight)")
    explanation: str = Field(..., description="Natural language explanation of this factor")
    details: Optional[str] = None


class MatchExplanation(BaseModel):
    """Comprehensive match explanation for a job"""
    job_id: uuid.UUID
    job_title: str
    company_name: str
    overall_score: int = Field(..., ge=0, le=100, description="Overall match score (0-100)")
    overall_summary: str = Field(..., description="Overall match summary")

    # Individual factor breakdowns
    embedding_similarity: MatchFactorExplanation
    skill_overlap: MatchFactorExplanation
    seniority_match: MatchFactorExplanation
    recency_decay: MatchFactorExplanation
    location_match: MatchFactorExplanation

    class Config:
        json_schema_extra = {
            "example": {
                "job_id": "123e4567-e89b-12d3-a456-426614174000",
                "job_title": "Senior Python Developer",
                "company_name": "TechCorp Inc.",
                "overall_score": 87,
                "overall_summary": "This is an excellent match for your profile. Your Python expertise aligns perfectly with the role, and the senior level matches your experience. The company is located in your preferred area.",
                "embedding_similarity": {
                    "score": 0.92,
                    "weight": 0.55,
                    "weighted_contribution": 0.506,
                    "explanation": "Your profile shows strong alignment with this role based on ML analysis of your experience, skills, and preferences.",
                    "details": "Profile similarity: 92%"
                },
                "skill_overlap": {
                    "score": 0.80,
                    "weight": 0.20,
                    "weighted_contribution": 0.16,
                    "explanation": "You have 4 out of 5 required skills for this position.",
                    "details": "Matching skills: Python, FastAPI, PostgreSQL, Docker"
                },
                "seniority_match": {
                    "score": 1.0,
                    "weight": 0.10,
                    "weighted_contribution": 0.10,
                    "explanation": "Your seniority level exactly matches the job requirements.",
                    "details": "You: Senior, Job: Senior"
                },
                "recency_decay": {
                    "score": 0.95,
                    "weight": 0.10,
                    "weighted_contribution": 0.095,
                    "explanation": "This is a fresh posting from 2 days ago.",
                    "details": "Posted 2 days ago"
                },
                "location_match": {
                    "score": 1.0,
                    "weight": 0.05,
                    "weighted_contribution": 0.05,
                    "explanation": "The job location matches your preferences perfectly.",
                    "details": "Remote position"
                }
            }
        }
