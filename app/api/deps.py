from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from typing import List, Callable
from app.core.database import get_db
from app.core.security import verify_token
from app.core.cache import get_cached_user, set_cached_user
from app.models.user import User, UserRole
from app.models.company import Company
import uuid

security = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db)
) -> User:
    """Get current authenticated user with company relationship"""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    # Verify token
    user_id = await verify_token(credentials.credentials, "access")
    if user_id is None:
        raise credentials_exception

    # Check cache first
    cached = await get_cached_user(user_id)
    if cached is not None:
        return cached

    # Cache miss — load from database with company relationship
    result = await db.execute(
        select(User)
        .options(selectinload(User.company))
        .where(User.id == uuid.UUID(user_id))
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise credentials_exception

    await set_cached_user(user_id, user)
    return user


def require_roles(allowed_roles: List[UserRole]) -> Callable:
    """Dependency factory for role-based access control"""
    def role_dependency(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied. Required roles: {[role.value for role in allowed_roles]}"
            )
        return current_user
    return role_dependency


# Common role dependencies
get_job_seeker = require_roles([UserRole.JOB_SEEKER])
get_company_user = require_roles([UserRole.COMPANY_RECRUITER, UserRole.COMPANY_ADMIN])
get_company_recruiter = require_roles([UserRole.COMPANY_RECRUITER, UserRole.COMPANY_ADMIN])
get_company_admin = require_roles([UserRole.COMPANY_ADMIN])


async def get_company_user_with_verification(
    current_user: User = Depends(get_company_user),
    db: AsyncSession = Depends(get_db)
) -> User:
    """Get company user and verify they have an active company"""
    if not current_user.company_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Company user must be associated with a company"
        )
    
    if not current_user.company or not current_user.company.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Associated company is not active"
        )
    
    return current_user


def require_company_access(current_user: User, company_id: uuid.UUID):
    """Verify that a company user has access to the specified company"""
    if current_user.company_id != company_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied. You can only access resources for your own company"
        )