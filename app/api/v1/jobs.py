from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from app.core.database import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.models.job import Job
from app.schemas.job import Job as JobSchema
import uuid

router = APIRouter()


@router.get("/{job_id}", response_model=JobSchema)
async def get_job(
    job_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get a specific job by ID"""
    job = db.query(Job).filter(Job.id == job_id, Job.is_active == True).first()
    
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    return job


@router.get("/discover", response_model=List[JobSchema])
async def discover_jobs(
    limit: int = Query(20, ge=1, le=50),
    cursor: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get personalized job recommendations (discover feed)
    
    Note: This is a simplified version. The full implementation would include:
    - ML scoring based on user embeddings
    - Filtering out already swiped jobs
    - Complex ranking algorithm as described in CLAUDE.md
    """
    
    # For now, return active jobs that user hasn't swiped on
    # This is a placeholder - full ML implementation needed
    from sqlalchemy import and_, not_, exists
    from app.models.swipe import Swipe
    
    jobs_query = db.query(Job).filter(
        and_(
            Job.is_active == True,
            not_(exists().where(
                and_(
                    Swipe.job_id == Job.id,
                    Swipe.user_id == current_user.id
                )
            ))
        )
    ).order_by(Job.created_at.desc()).limit(limit)
    
    jobs = jobs_query.all()
    
    # Add placeholder scores (to be replaced with ML scoring)
    job_results = []
    for job in jobs:
        job_dict = JobSchema.from_orm(job).dict()
        job_dict["score"] = 75  # Placeholder score
        job_results.append(JobSchema(**job_dict))
    
    return job_results