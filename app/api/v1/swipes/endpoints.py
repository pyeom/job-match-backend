from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.core.database import get_db
from app.api.deps import get_current_user, get_job_seeker
from app.models.user import User
from app.models.job import Job
from app.models.swipe import Swipe
from app.models.application import Application
from app.schemas.swipe import SwipeCreate, Swipe as SwipeSchema

router = APIRouter()


@router.post("", response_model=SwipeSchema)
async def create_swipe(
    swipe_data: SwipeCreate,
    current_user: User = Depends(get_job_seeker),  # Only job seekers can swipe
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

    # If RIGHT swipe, create or update application and potentially update user embedding
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
                status="ACTIVE"
            )
            db.add(application)
            await db.commit()

        # Update user embedding based on right swipe history (as per CLAUDE.md)
        await _update_user_embedding_if_needed(current_user, db)

    return swipe


async def _update_user_embedding_if_needed(user: User, db):
    """Update user embedding based on right swipe history after threshold"""
    from app.services.embedding_service import embedding_service

    # Count user's right swipes
    result = await db.execute(
        select(func.count(Swipe.id))
        .where(Swipe.user_id == user.id, Swipe.direction == "RIGHT")
    )
    right_swipe_count = result.scalar()

    # Update embedding after 5 right swipes, then every 3 additional swipes
    should_update = (
        (right_swipe_count == 5) or  # First update after 5 swipes
        (right_swipe_count > 5 and (right_swipe_count - 5) % 3 == 0)  # Every 3 swipes after
    )

    if not should_update:
        return

    try:
        # Get jobs from recent right swipes (limit to last 10 for performance)
        result = await db.execute(
            select(Job.job_embedding)
            .join(Swipe, Job.id == Swipe.job_id)
            .where(
                Swipe.user_id == user.id,
                Swipe.direction == "RIGHT",
                Job.job_embedding.isnot(None)
            )
            .order_by(Swipe.created_at.desc())
            .limit(10)
        )
        job_embeddings = [row[0] for row in result.all()]

        if not job_embeddings:
            return

        # Generate base embedding if user doesn't have one
        if not user.profile_embedding:
            user.profile_embedding = embedding_service.generate_user_embedding(
                headline=user.headline,
                skills=user.skills,
                preferences=user.preferred_locations
            )

        # Update embedding combining profile with right swipe history
        updated_embedding = embedding_service.update_user_embedding_with_history(
            base_embedding=user.profile_embedding,
            liked_job_embeddings=job_embeddings,
            alpha=0.3  # 30% profile, 70% history as per CLAUDE.md
        )

        user.profile_embedding = updated_embedding
        await db.commit()

        print(f"Updated user {user.id} embedding after {right_swipe_count} right swipes")

    except Exception as e:
        print(f"Failed to update user embedding for {user.id}: {e}")
        # Don't fail the swipe if embedding update fails
