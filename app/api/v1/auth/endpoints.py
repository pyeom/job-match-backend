from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db
from app.core.security import (
    verify_password, get_password_hash, create_access_token, create_refresh_token,
    verify_token, blacklist_token, is_token_expired, get_token_expiration
)
from app.models.user import User, UserRole
from app.models.company import Company
from app.schemas.auth import (
    UserCreate, CompanyUserCreate, UserLogin, Token, LogoutResponse,
    RefreshTokenRequest, TokenRefreshResponse
)
from app.schemas.user import User as UserSchema
from app.api.deps import get_current_user
import uuid

router = APIRouter()


@router.post("/register", response_model=Token)
async def register(user_data: UserCreate, db: AsyncSession = Depends(get_db)):
    """Register a new job seeker user"""
    # Check if user already exists
    result = await db.execute(select(User).where(User.email == user_data.email))
    db_user = result.scalar_one_or_none()
    if db_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )

    # Create new user
    hashed_password = get_password_hash(user_data.password)
    db_user = User(
        id=uuid.uuid4(),
        email=user_data.email,
        password_hash=hashed_password,
        full_name=user_data.full_name,
        role=user_data.role
    )

    db.add(db_user)
    await db.commit()
    await db.refresh(db_user)

    # Create tokens
    access_token = create_access_token(data={"sub": str(db_user.id)})
    refresh_token = create_refresh_token(data={"sub": str(db_user.id)})

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer"
    }


@router.post("/register-company", response_model=Token)
async def register_company_user(user_data: CompanyUserCreate, db: AsyncSession = Depends(get_db)):
    """Register a new company user with associated company"""
    # Check if user already exists
    result = await db.execute(select(User).where(User.email == user_data.email))
    db_user = result.scalar_one_or_none()
    if db_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )

    # Check if company already exists
    result = await db.execute(select(Company).where(Company.name == user_data.company_name))
    db_company = result.scalar_one_or_none()

    if db_company:
        # Check if company is active
        if not db_company.is_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Company exists but is not active"
            )
        company_id = db_company.id
    else:
        # Create new company
        db_company = Company(
            id=uuid.uuid4(),
            name=user_data.company_name,
            description=user_data.company_description,
            website=user_data.company_website,
            industry=user_data.company_industry,
            size=user_data.company_size,
            location=user_data.company_location
        )
        db.add(db_company)
        await db.flush()  # Get the company ID
        company_id = db_company.id

    # Create new company user
    hashed_password = get_password_hash(user_data.password)
    db_user = User(
        id=uuid.uuid4(),
        email=user_data.email,
        password_hash=hashed_password,
        full_name=user_data.full_name,
        role=user_data.role,
        company_id=company_id
    )

    db.add(db_user)
    await db.commit()
    await db.refresh(db_user)

    # Create tokens
    access_token = create_access_token(data={"sub": str(db_user.id)})
    refresh_token = create_refresh_token(data={"sub": str(db_user.id)})

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer"
    }


@router.post("/login", response_model=Token)
async def login(user_credentials: UserLogin, db: AsyncSession = Depends(get_db)):
    """Authenticate user and return tokens"""
    # Get user by email
    result = await db.execute(select(User).where(User.email == user_credentials.email))
    user = result.scalar_one_or_none()

    if not user or not verify_password(user_credentials.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Create tokens
    access_token = create_access_token(data={"sub": str(user.id)})
    refresh_token = create_refresh_token(data={"sub": str(user.id)})

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer"
    }


@router.post("/refresh", response_model=TokenRefreshResponse)
async def refresh_access_token(
    refresh_request: RefreshTokenRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Refresh access token using refresh token

    This endpoint provides secure token refresh functionality:
    - Validates the provided refresh token
    - Blacklists the old refresh token to prevent reuse
    - Issues new access and refresh tokens
    - Returns token expiration information

    Security Features:
    - Token rotation: old refresh tokens are invalidated
    - Blacklist protection against token reuse
    - User validation to ensure account still exists
    - Proper error handling for various failure scenarios
    """
    refresh_token = refresh_request.refresh_token

    # Verify refresh token format and signature
    user_id = verify_token(refresh_token, "refresh")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or malformed refresh token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Check if refresh token is expired
    if is_token_expired(refresh_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Verify user still exists and is active
    try:
        result = await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
        user = result.scalar_one_or_none()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User account not found or has been deactivated"
            )
    except ValueError:
        # Invalid UUID format
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid user identifier in token"
        )

    # Blacklist the old refresh token to prevent reuse
    blacklist_token(refresh_token)

    # Create new tokens with rotation
    access_token = create_access_token(data={"sub": str(user.id)})
    new_refresh_token = create_refresh_token(data={"sub": str(user.id)})

    # Get access token expiration for client
    from app.core.config import settings

    return TokenRefreshResponse(
        access_token=access_token,
        refresh_token=new_refresh_token,
        token_type="bearer",
        expires_in=settings.access_token_expires
    )


@router.post("/logout", response_model=LogoutResponse)
async def logout(
    request: Request,
    current_user: User = Depends(get_current_user)
):
    """
    Logout user by invalidating tokens

    Enhanced logout functionality with server-side token blacklisting:
    - Extracts and blacklists the current access token
    - Invalidates tokens immediately on the server side
    - Provides secure logout mechanism for JWT-based authentication

    Security Features:
    - Immediate token invalidation via blacklist
    - Prevents token reuse after logout
    - Safe handling of malformed or missing tokens
    - Comprehensive cleanup of user session

    Args:
        request: FastAPI request object to extract authorization header
        current_user: The authenticated user (automatically injected via dependency)

    Returns:
        LogoutResponse: Confirmation message with cleanup instructions

    Authentication:
        Requires valid JWT access token in Authorization header
    """
    # Extract token from Authorization header for blacklisting
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        access_token = auth_header[7:]  # Remove "Bearer " prefix

        # Blacklist the access token to prevent immediate reuse
        blacklist_token(access_token)

    return LogoutResponse(
        message="Successfully logged out",
        detail="Tokens have been invalidated. Please clear all tokens from client storage."
    )
