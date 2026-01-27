"""
Interview Questions Schemas

Pydantic models for AI-powered interview question predictions.
"""

from pydantic import BaseModel, Field
from typing import List
from uuid import UUID


class InterviewQuestion(BaseModel):
    """A single interview question with metadata"""
    question: str = Field(..., description="The interview question text")
    category: str = Field(..., description="Question category (behavioral, technical, situational, company-specific)")
    difficulty: str = Field(..., description="Difficulty level (easy, medium, hard)")
    tip: str = Field(..., description="Helpful tip for answering this question")
    related_skills: List[str] = Field(default_factory=list, description="Skills this question tests")


class InterviewQuestionsByCategory(BaseModel):
    """Questions organized by category"""
    behavioral: List[InterviewQuestion] = Field(default_factory=list, description="Behavioral/cultural fit questions")
    technical: List[InterviewQuestion] = Field(default_factory=list, description="Technical skill questions")
    situational: List[InterviewQuestion] = Field(default_factory=list, description="Situational/problem-solving questions")
    company_specific: List[InterviewQuestion] = Field(default_factory=list, description="Company culture and role-specific questions")


class InterviewQuestionsResponse(BaseModel):
    """Complete interview questions prediction response"""
    job_id: UUID
    job_title: str
    company_name: str
    summary: str = Field(..., description="Brief summary of what to expect in the interview")
    questions: InterviewQuestionsByCategory
    total_questions: int = Field(..., description="Total number of questions generated")
    preparation_tips: List[str] = Field(..., description="General tips for interview preparation")

    class Config:
        json_schema_extra = {
            "example": {
                "job_id": "123e4567-e89b-12d3-a456-426614174000",
                "job_title": "Senior Python Developer",
                "company_name": "TechCorp Inc.",
                "summary": "Based on the job requirements and company profile, expect a mix of technical Python questions, behavioral scenarios, and system design discussions. The interview will likely focus on FastAPI, database design, and your ability to work in a collaborative environment.",
                "questions": {
                    "behavioral": [
                        {
                            "question": "Tell me about a time when you had to collaborate with a difficult team member. How did you handle it?",
                            "category": "behavioral",
                            "difficulty": "medium",
                            "tip": "Use the STAR method (Situation, Task, Action, Result) and focus on positive outcomes",
                            "related_skills": ["Communication", "Teamwork"]
                        }
                    ],
                    "technical": [
                        {
                            "question": "Explain the difference between synchronous and asynchronous programming in Python. When would you use each?",
                            "category": "technical",
                            "difficulty": "medium",
                            "tip": "Relate your answer to FastAPI and async/await patterns, provide real-world examples",
                            "related_skills": ["Python", "FastAPI"]
                        }
                    ],
                    "situational": [
                        {
                            "question": "You're facing a production database issue affecting users. Walk me through your debugging approach.",
                            "category": "situational",
                            "difficulty": "hard",
                            "tip": "Demonstrate systematic problem-solving and understanding of production best practices",
                            "related_skills": ["PostgreSQL", "Problem-solving"]
                        }
                    ],
                    "company_specific": [
                        {
                            "question": "What interests you most about working at TechCorp Inc.?",
                            "category": "company_specific",
                            "difficulty": "easy",
                            "tip": "Research the company's values, recent projects, and culture. Show genuine interest",
                            "related_skills": []
                        }
                    ]
                },
                "total_questions": 15,
                "preparation_tips": [
                    "Review Python async/await patterns and FastAPI framework",
                    "Prepare examples of past projects involving database optimization",
                    "Research TechCorp Inc.'s recent product launches and company values",
                    "Practice explaining technical concepts to non-technical stakeholders",
                    "Prepare thoughtful questions about the team structure and development process"
                ]
            }
        }
