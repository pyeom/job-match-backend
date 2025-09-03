from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from app.core.database import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.models.application import Application
from app.schemas.application import Application as ApplicationSchema, ApplicationUpdate
import uuid

router = APIRouter()


@router.get("/", response_model=List[ApplicationSchema])
async def get_user_applications(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all applications for current user"""
    applications = db.query(Application).filter(
        Application.user_id == current_user.id
    ).order_by(Application.created_at.desc()).all()
    
    return applications


@router.get("/{application_id}", response_model=ApplicationSchema)
async def get_application(
    application_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get a specific application"""
    application = db.query(Application).filter(
        Application.id == application_id,
        Application.user_id == current_user.id
    ).first()
    
    if not application:
        raise HTTPException(status_code=404, detail="Application not found")
    
    return application


@router.patch("/{application_id}", response_model=ApplicationSchema)
async def update_application(
    application_id: uuid.UUID,
    application_update: ApplicationUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update application status or notes"""
    application = db.query(Application).filter(
        Application.id == application_id,
        Application.user_id == current_user.id
    ).first()
    
    if not application:
        raise HTTPException(status_code=404, detail="Application not found")
    
    update_data = application_update.dict(exclude_unset=True)
    
    for field, value in update_data.items():
        setattr(application, field, value)
    
    db.commit()
    db.refresh(application)
    
    return application