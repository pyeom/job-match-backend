from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.models.job import Job
from app.models.swipe import Swipe
from app.models.application import Application
from app.schemas.swipe import SwipeCreate, Swipe as SwipeSchema

router = APIRouter()


@router.post("/", response_model=SwipeSchema)
async def create_swipe(
    swipe_data: SwipeCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Create a new swipe (and application if RIGHT)"""
    
    # Validate job exists
    result = await db.execute(select(Job).where(Job.id == swipe_data.job_id, Job.is_active == True))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    # Validate direction
    if swipe_data.direction not in ["LEFT", "RIGHT"]:
        raise HTTPException(status_code=400, detail="Direction must be LEFT or RIGHT")
    
    # Check if swipe already exists (update if so)
    result = await db.execute(select(Swipe).where(
        Swipe.user_id == current_user.id,
        Swipe.job_id == swipe_data.job_id
    ))
    existing_swipe = result.scalar_one_or_none()
    
    if existing_swipe:
        # Update existing swipe
        existing_swipe.direction = swipe_data.direction
        await db.commit()
        await db.refresh(existing_swipe)
        swipe = existing_swipe
    else:
        # Create new swipe
        swipe = Swipe(
            user_id=current_user.id,
            job_id=swipe_data.job_id,
            direction=swipe_data.direction
        )
        db.add(swipe)
        await db.commit()
        await db.refresh(swipe)
    
    # If RIGHT swipe, create or update application
    if swipe_data.direction == "RIGHT":
        result = await db.execute(select(Application).where(
            Application.user_id == current_user.id,
            Application.job_id == swipe_data.job_id
        ))
        existing_application = result.scalar_one_or_none()
        
        if not existing_application:
            application = Application(
                user_id=current_user.id,
                job_id=swipe_data.job_id,
                status="SUBMITTED"
            )
            db.add(application)
            await db.commit()
    
    return swipe