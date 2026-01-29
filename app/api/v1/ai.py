"""
AI-powered endpoints for enhanced user experience.

This module provides AI-driven features like match explanations
and personalized insights.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Body
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
import logging

from app.core.database import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.repositories.job_repository import JobRepository
from app.repositories.document_repository import DocumentRepository
from app.schemas.match_explanation import MatchExplanation
from app.schemas.interview_questions import InterviewQuestionsResponse
from app.schemas.resume_review import ResumeReviewRequest, ResumeReviewResponse
from app.schemas.resume_parser import ResumeParseRequest, ProfileAutoFillResponse
from app.services.match_explanation_service import match_explanation_service
from app.services.interview_predictor_service import interview_predictor_service
from app.services.resume_review_service import resume_review_service
from app.services.resume_parser_service import resume_parser_service
from app.services.user_service import user_service
from app.services.document_parser import document_parser
from app.services.storage_service import storage_service

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/match-explanation", response_model=MatchExplanation)
async def get_match_explanation(
    job_id: UUID = Query(..., description="UUID of the job to explain"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get AI-powered match explanation for a specific job.

    This endpoint provides a detailed breakdown of why a job matches (or doesn't match)
    the current user's profile. It explains each component of the hybrid scoring algorithm
    in natural language.

    Returns:
    - Overall match score (0-100)
    - Natural language summary of the match
    - Detailed breakdown of each scoring factor:
        - Embedding similarity (55% weight) - ML-based profile alignment
        - Skill overlap (20% weight) - Direct skill matching
        - Seniority match (10% weight) - Career level alignment
        - Recency (10% weight) - How fresh the posting is
        - Location match (5% weight) - Geographic fit

    Each factor includes:
    - Normalized score (0-1)
    - Weight in overall calculation
    - Contribution to final score
    - Human-readable explanation
    - Supporting details

    Requires:
    - User must be authenticated
    - Job must exist and be active
    - User must have a profile embedding for best results
    """

    # Get job with company information
    job_repo = JobRepository()
    job = await job_repo.get_job_with_company(db, job_id)

    if not job:
        raise HTTPException(
            status_code=404,
            detail="Job not found"
        )

    if not job.is_active:
        raise HTTPException(
            status_code=400,
            detail="Job is no longer active"
        )

    # Check if user has profile embedding
    if current_user.profile_embedding is None or (hasattr(current_user.profile_embedding, '__len__') and len(current_user.profile_embedding) == 0):
        raise HTTPException(
            status_code=400,
            detail="User profile embedding not available. Please complete your profile to get match explanations."
        )

    # Check if job has embedding
    if job.job_embedding is None or (hasattr(job.job_embedding, '__len__') and len(job.job_embedding) == 0):
        raise HTTPException(
            status_code=400,
            detail="Job embedding not available. This job may be too old or improperly configured."
        )

    # Generate match explanation
    try:
        explanation = match_explanation_service.generate_match_explanation(
            job_id=str(job.id),
            job_title=job.title,
            company_name=job.company.name if job.company else "Unknown Company",
            user_embedding=current_user.profile_embedding,
            job_embedding=job.job_embedding,
            user_skills=current_user.skills,
            user_seniority=current_user.seniority,
            user_preferences=current_user.preferred_locations,
            job_tags=job.tags,
            job_seniority=job.seniority,
            job_location=job.location,
            job_remote=job.remote or False,
            job_created_at=job.created_at
        )

        return explanation

    except Exception as e:
        logger.error(f"Error generating match explanation for job {job_id}, user {current_user.id}: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to generate match explanation. Please try again later."
        )


@router.get("/interview-questions", response_model=InterviewQuestionsResponse)
async def get_interview_questions(
    job_id: UUID = Query(..., description="UUID of the job to get interview questions for"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get AI-powered interview question predictions for a specific job.

    This endpoint analyzes the job requirements, skills, seniority level, and company
    information to generate likely interview questions that candidates might encounter.

    Returns:
    - Job and company information
    - Interview summary and expectations
    - Categorized questions:
        - Behavioral: Questions about past experiences and work style
        - Technical: Skill-specific technical questions
        - Situational: Problem-solving and scenario-based questions
        - Company-specific: Questions about the company and role fit
    - Preparation tips: Personalized advice for interview preparation
    - Helpful tips for answering each question

    Each question includes:
    - Question text
    - Category (behavioral, technical, situational, company-specific)
    - Difficulty level (easy, medium, hard)
    - Helpful tip for answering
    - Related skills being tested

    Requires:
    - User must be authenticated
    - Job must exist and be active
    """

    # Get job with company information
    job_repo = JobRepository()
    job = await job_repo.get_job_with_company(db, job_id)

    if not job:
        raise HTTPException(
            status_code=404,
            detail="Job not found"
        )

    if not job.is_active:
        raise HTTPException(
            status_code=400,
            detail="Job is no longer active"
        )

    if not job.company:
        raise HTTPException(
            status_code=400,
            detail="Job company information not available"
        )

    # Generate interview questions
    try:
        interview_questions = interview_predictor_service.generate_interview_questions(
            job=job,
            company=job.company
        )

        return interview_questions

    except Exception as e:
        logger.error(f"Error generating interview questions for job {job_id}, user {current_user.id}: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to generate interview questions. Please try again later."
        )


@router.post("/resume-review", response_model=ResumeReviewResponse)
async def review_resume(
    request: ResumeReviewRequest = Body(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get AI-powered resume review with improvement suggestions.

    This endpoint analyzes an uploaded resume and provides comprehensive feedback including:
    - Overall quality score (0-100)
    - Structure, content, and formatting scores
    - Section-by-section analysis with specific feedback
    - Keyword analysis (if target job specified)
    - Actionable improvement suggestions
    - Strengths and weaknesses identification

    The analysis covers:
    - Resume structure and organization
    - Content quality and impact
    - Use of action verbs and quantified achievements
    - Formatting and readability
    - Keyword optimization (for target job)
    - Professional presentation

    Args:
        document_id: UUID of the uploaded resume document
        target_job_id: Optional UUID of a job to analyze resume against

    Returns:
        Comprehensive resume review with scores, analysis, and suggestions

    Requires:
        - User must be authenticated
        - Document must exist and belong to the user
        - Document must be a resume type
        - Document must have extractable text content
    """

    # Get the document
    doc_repo = DocumentRepository()
    document = await doc_repo.get(db, request.document_id)

    if not document:
        raise HTTPException(
            status_code=404,
            detail="Document not found"
        )

    # Verify document belongs to current user
    if document.user_id != current_user.id:
        raise HTTPException(
            status_code=403,
            detail="You don't have permission to access this document"
        )

    # Verify document is a resume
    if document.document_type != "resume":
        raise HTTPException(
            status_code=400,
            detail="Document must be of type 'resume'. This document is a '{document.document_type}'."
        )

    # Get resume text content
    resume_text = None

    # First try to use cached extracted_text
    if document.extracted_text:
        resume_text = document.extracted_text
    else:
        # Extract text from the document file
        try:
            # Read file from storage
            file_content = await storage_service.read_file(document.storage_path)

            if not file_content:
                raise HTTPException(
                    status_code=400,
                    detail="Could not read document file from storage"
                )

            # Extract text using document parser
            resume_text = document_parser.extract_text(file_content, document.file_type)

            if not resume_text:
                raise HTTPException(
                    status_code=400,
                    detail="Could not extract text from document. The file may be corrupted or in an unsupported format."
                )

            # Cache the extracted text for future use
            document.extracted_text = resume_text
            await db.commit()

        except Exception as e:
            logger.error(f"Error reading/parsing document {request.document_id}: {e}")
            raise HTTPException(
                status_code=500,
                detail="Failed to process document file"
            )

    # Get target job if specified
    target_job = None
    if request.target_job_id:
        job_repo = JobRepository()
        target_job = await job_repo.get(db, request.target_job_id)

        if not target_job:
            raise HTTPException(
                status_code=404,
                detail="Target job not found"
            )

        if not target_job.is_active:
            raise HTTPException(
                status_code=400,
                detail="Target job is no longer active"
            )

    # Analyze the resume
    try:
        review = resume_review_service.analyze_resume(
            resume_text=resume_text,
            resume_document=document,
            target_job=target_job
        )

        logger.info(
            f"Resume review completed for document {request.document_id}, "
            f"user {current_user.id}, score: {review.overall_score}"
        )

        return review

    except Exception as e:
        logger.error(f"Error analyzing resume {request.document_id}, user {current_user.id}: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to analyze resume. Please try again later."
        )


@router.post("/parse-resume", response_model=ProfileAutoFillResponse)
async def parse_resume(
    request: ResumeParseRequest = Body(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Parse resume using AI and optionally auto-fill user profile.

    This endpoint uses AI/NLP to extract structured information from an uploaded resume:
    - Contact information (name, email, phone, LinkedIn, GitHub, portfolio)
    - Professional summary and headline
    - Work experience (title, company, dates, description)
    - Education (degree, institution, field of study, dates)
    - Skills (categorized as technical, soft skills, languages, certifications)

    The parsing uses a hybrid approach combining:
    - Regex patterns for structured data (emails, phones, dates)
    - NLP techniques for section detection
    - Keyword matching for skills and technologies
    - Heuristics for experience and education extraction

    If auto_fill_profile is True, the parsed data will automatically update
    the user's profile fields that are currently empty. Existing data is preserved.

    Args:
        document_id: UUID of the uploaded resume document
        auto_fill_profile: Whether to automatically update profile with parsed data

    Returns:
        Parsed resume data and profile update status

    Requires:
        - User must be authenticated
        - Document must exist and belong to the user
        - Document must be of type 'resume'
        - Document must have extractable text content
    """

    # Get the document
    doc_repo = DocumentRepository()
    document = await doc_repo.get(db, request.document_id)

    if not document:
        raise HTTPException(
            status_code=404,
            detail="Document not found"
        )

    # Verify document belongs to current user
    if document.user_id != current_user.id:
        raise HTTPException(
            status_code=403,
            detail="You don't have permission to access this document"
        )

    # Verify document is a resume
    if document.document_type != "resume":
        raise HTTPException(
            status_code=400,
            detail=f"Document must be of type 'resume'. This document is a '{document.document_type}'."
        )

    # Get resume text content
    resume_text = None

    # First try to use cached extracted_text
    if document.extracted_text:
        resume_text = document.extracted_text
    else:
        # Extract text from the document file
        try:
            # Read file from storage
            file_content = await storage_service.read_file(document.storage_path)

            if not file_content:
                raise HTTPException(
                    status_code=400,
                    detail="Could not read document file from storage"
                )

            # Extract text using document parser
            resume_text = document_parser.extract_text(file_content, document.file_type)

            if not resume_text:
                raise HTTPException(
                    status_code=400,
                    detail="Could not extract text from document. The file may be corrupted or in an unsupported format."
                )

            # Cache the extracted text for future use
            document.extracted_text = resume_text
            await db.commit()

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error reading/parsing document {request.document_id}: {e}")
            raise HTTPException(
                status_code=500,
                detail="Failed to process document file"
            )

    # Parse the resume
    try:
        parsed_data = resume_parser_service.parse_resume(
            resume_text=resume_text,
            document_id=str(request.document_id)
        )

        logger.info(
            f"Resume parsed for document {request.document_id}, "
            f"user {current_user.id}, confidence: {parsed_data.confidence_score:.2f}"
        )

    except Exception as e:
        logger.error(f"Error parsing resume {request.document_id}, user {current_user.id}: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to parse resume. Please try again later."
        )

    # Auto-fill profile if requested
    profile_updated = False
    fields_updated = []

    if request.auto_fill_profile:
        try:
            updated_user, fields_updated = await user_service.update_profile_from_resume(
                db=db,
                user=current_user,
                parsed_data=parsed_data
            )
            profile_updated = bool(fields_updated)

            logger.info(
                f"Profile auto-filled for user {current_user.id}. "
                f"Fields updated: {fields_updated}"
            )

        except Exception as e:
            logger.error(f"Error auto-filling profile for user {current_user.id}: {e}")
            # Don't fail the entire request if auto-fill fails
            # Just log the error and continue

    return ProfileAutoFillResponse(
        document_id=request.document_id,
        parsed_data=parsed_data,
        profile_updated=profile_updated,
        fields_updated=fields_updated,
        message="Resume parsed successfully" + (
            f" and profile updated ({len(fields_updated)} fields)"
            if profile_updated
            else ""
        )
    )
