from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db
from app.core.security import (
    verify_password, verify_password_legacy, get_password_hash,
    create_access_token, create_refresh_token,
    verify_token, blacklist_token, is_token_expired, get_token_expiration,
    invalidate_user_tokens,
    get_device_id_from_token, get_token_expires_at, _get_token_hash,
    store_device_session, update_device_session, revoke_device_session,
    revoke_all_user_sessions, get_user_sessions,
)
from app.models.user import User, UserRole
from app.models.company import Company
from app.schemas.auth import (
    UserCreate, CompanyUserCreate, UserLogin, Token, LogoutResponse,
    RefreshTokenRequest, TokenRefreshResponse, RefreshTokenLogout,
    DeviceSession, DeviceListResponse, LogoutAllResponse, RevokeDeviceResponse,
)
from app.schemas.user import User as UserSchema
from app.api.deps import get_current_user
from app.services.embedding_service import embedding_service
from app.services.rate_limit_service import rate_limit_service
from app.services.email_service import (
    generate_verification_token,
    store_verification_token,
    consume_verification_token,
    send_verification_email,
    store_password_reset_token,
    consume_password_reset_token,
    send_password_reset_email,
)
import uuid
from app.core.config import settings

router = APIRouter()


@router.post("/register", response_model=Token)
async def register(
    request: Request,
    user_data: UserCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Register a new job seeker user"""
    # Rate limit: 10 registrations per IP per hour
    client_ip = request.client.host if request.client else "unknown"
    is_allowed, retry_after = await rate_limit_service.check_rate_limit(
        key=f"register:ip:{client_ip}",
        max_requests=10,
        window_seconds=3600,
    )
    if not is_allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many registration attempts. Please try again later.",
            headers={"Retry-After": str(retry_after)},
        )

    # Check if user already exists
    result = await db.execute(select(User).where(User.email == user_data.email))
    db_user = result.scalar_one_or_none()
    if db_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )

    # Create new user (email_verified defaults to False)
    hashed_password = get_password_hash(user_data.password)
    db_user = User(
        id=uuid.uuid4(),
        email=user_data.email,
        password_hash=hashed_password,
        full_name=user_data.full_name,
        role=user_data.role,
        email_verified=False,
    )

    db.add(db_user)
    await db.flush()  # Get the user ID before generating embedding

    # Generate initial profile embedding (will be zero vector if no profile data yet)
    try:
        profile_embedding = embedding_service.generate_user_embedding(
            headline=db_user.headline,
            skills=db_user.skills,
            preferences=db_user.preferred_locations
        )
        db_user.profile_embedding = profile_embedding
    except Exception as e:
        # Log error but don't fail registration
        print(f"Failed to generate profile embedding for user {db_user.id}: {e}")

    await db.commit()
    await db.refresh(db_user)

    # Issue and store email verification token, then send email in background
    verify_token_value = generate_verification_token()
    await store_verification_token(verify_token_value, str(db_user.id))
    background_tasks.add_task(
        send_verification_email,
        db_user.email,
        db_user.full_name or "",
        verify_token_value,
    )

    # Create tokens with device session tracking
    device_id = str(uuid.uuid4())
    device_name = user_data.device_name or "Unknown Device"
    platform_name = user_data.platform or "unknown"

    access_token = create_access_token(data={"sub": str(db_user.id)})
    refresh_token = create_refresh_token(data={"sub": str(db_user.id), "did": device_id})

    token_hash = _get_token_hash(refresh_token)
    expires_at = get_token_expires_at(refresh_token)
    await store_device_session(
        str(db_user.id), device_id, token_hash, expires_at,
        device_name, platform_name,
    )

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": settings.access_token_expires,
    }


@router.post("/register-company", response_model=Token)
async def register_company_user(
    request: Request,
    user_data: CompanyUserCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Register a new company user with associated company"""
    # Rate limit: 10 registrations per IP per hour (shared bucket with /register)
    client_ip = request.client.host if request.client else "unknown"
    is_allowed, retry_after = await rate_limit_service.check_rate_limit(
        key=f"register:ip:{client_ip}",
        max_requests=10,
        window_seconds=3600,
    )
    if not is_allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many registration attempts. Please try again later.",
            headers={"Retry-After": str(retry_after)},
        )

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

    # Create new company user (email_verified defaults to False)
    hashed_password = get_password_hash(user_data.password)
    db_user = User(
        id=uuid.uuid4(),
        email=user_data.email,
        password_hash=hashed_password,
        full_name=user_data.full_name,
        role=user_data.role,
        company_id=company_id,
        email_verified=False,
    )

    db.add(db_user)
    await db.flush()  # Get the user ID before generating embedding

    # Generate initial profile embedding (company users may not need it, but good to have)
    try:
        profile_embedding = embedding_service.generate_user_embedding(
            headline=db_user.headline,
            skills=db_user.skills,
            preferences=db_user.preferred_locations
        )
        db_user.profile_embedding = profile_embedding
    except Exception as e:
        # Log error but don't fail registration
        print(f"Failed to generate profile embedding for user {db_user.id}: {e}")

    await db.commit()
    await db.refresh(db_user)

    # Issue and store email verification token, then send email in background
    verify_token_value = generate_verification_token()
    await store_verification_token(verify_token_value, str(db_user.id))
    background_tasks.add_task(
        send_verification_email,
        db_user.email,
        db_user.full_name or "",
        verify_token_value,
    )

    # Create tokens with device session tracking
    device_id = str(uuid.uuid4())
    device_name = user_data.device_name or "Unknown Device"
    platform_name = user_data.platform or "unknown"

    access_token = create_access_token(data={"sub": str(db_user.id)})
    refresh_token = create_refresh_token(data={"sub": str(db_user.id), "did": device_id})

    token_hash = _get_token_hash(refresh_token)
    expires_at = get_token_expires_at(refresh_token)
    await store_device_session(
        str(db_user.id), device_id, token_hash, expires_at,
        device_name, platform_name,
    )

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": settings.access_token_expires,
    }


@router.post("/login", response_model=Token)
async def login(
    request: Request,
    user_credentials: UserLogin,
    db: AsyncSession = Depends(get_db),
):
    """Authenticate user and return tokens"""
    # Rate limit: 5 attempts per email per 15 minutes
    is_allowed, retry_after = await rate_limit_service.check_rate_limit(
        key=f"login:email:{user_credentials.email.lower()}",
        max_requests=5,
        window_seconds=900,
    )
    if not is_allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts for this account. Please try again later.",
            headers={"Retry-After": str(retry_after)},
        )

    # Rate limit: 20 attempts per IP per 15 minutes
    client_ip = request.client.host if request.client else "unknown"
    is_allowed, retry_after = await rate_limit_service.check_rate_limit(
        key=f"login:ip:{client_ip}",
        max_requests=20,
        window_seconds=900,
    )
    if not is_allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts from this address. Please try again later.",
            headers={"Retry-After": str(retry_after)},
        )

    # Get user by email
    result = await db.execute(select(User).where(User.email == user_credentials.email))
    user = result.scalar_one_or_none()

    password_valid = user and verify_password(user_credentials.password, user.password_hash)
    if not password_valid and user:
        # Migration path: try the legacy truncation method for pre-existing hashes
        if verify_password_legacy(user_credentials.password, user.password_hash):
            user.password_hash = get_password_hash(user_credentials.password)
            await db.commit()
            password_valid = True

    if not user or not password_valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Create tokens with device session tracking
    device_id = str(uuid.uuid4())
    device_name = user_credentials.device_name or "Unknown Device"
    platform_name = user_credentials.platform or "unknown"

    access_token = create_access_token(data={"sub": str(user.id)})
    refresh_token = create_refresh_token(data={"sub": str(user.id), "did": device_id})

    token_hash = _get_token_hash(refresh_token)
    expires_at = get_token_expires_at(refresh_token)
    await store_device_session(
        str(user.id), device_id, token_hash, expires_at,
        device_name, platform_name,
    )

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": settings.access_token_expires,
    }


@router.post("/refresh", response_model=TokenRefreshResponse)
async def refresh_access_token(
    request: Request,
    refresh_request: RefreshTokenRequest,
    db: AsyncSession = Depends(get_db),
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
    # Rate limit: 30 refresh attempts per IP per 15 minutes
    client_ip = request.client.host if request.client else "unknown"
    is_allowed, retry_after = await rate_limit_service.check_rate_limit(
        key=f"refresh:ip:{client_ip}",
        max_requests=30,
        window_seconds=900,
    )
    if not is_allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many token refresh attempts. Please try again later.",
            headers={"Retry-After": str(retry_after)},
        )

    refresh_token = refresh_request.refresh_token

    # Verify refresh token format and signature
    user_id = await verify_token(refresh_token, "refresh")
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
    await blacklist_token(refresh_token)

    # Extract device_id from old token (may be None for old tokens without device tracking)
    device_id = get_device_id_from_token(refresh_token)

    # Create new tokens with rotation
    token_data: dict = {"sub": str(user.id)}
    if device_id:
        token_data["did"] = device_id

    access_token = create_access_token(data={"sub": str(user.id)})
    new_refresh_token = create_refresh_token(data=token_data)

    # Update device session with new token hash
    if device_id:
        new_token_hash = _get_token_hash(new_refresh_token)
        new_expires_at = get_token_expires_at(new_refresh_token)
        await update_device_session(str(user.id), device_id, new_token_hash, new_expires_at)

    # Get access token expiration for client
    return TokenRefreshResponse(
        access_token=access_token,
        refresh_token=new_refresh_token,
        token_type="bearer",
        expires_in=settings.access_token_expires
    )


@router.post("/logout", response_model=LogoutResponse)
async def logout(
    request: Request,
    body: RefreshTokenLogout = RefreshTokenLogout(),
    current_user: User = Depends(get_current_user),
):
    """Logout user by invalidating tokens and removing the device session."""
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        access_token = auth_header[7:]
        await blacklist_token(access_token)

    # If a refresh token is supplied, extract the device_id and remove that session
    if body.refresh_token:
        device_id = get_device_id_from_token(body.refresh_token)
        if device_id:
            await revoke_device_session(str(current_user.id), device_id)

    return LogoutResponse(
        message="Successfully logged out",
        detail="Tokens have been invalidated. Please clear all tokens from client storage."
    )


@router.post("/logout-all", response_model=LogoutAllResponse)
async def logout_all(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    """Revoke all active sessions for the current user across all devices."""
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        access_token = auth_header[7:]
        await blacklist_token(access_token)

    devices_revoked = await revoke_all_user_sessions(str(current_user.id))

    return LogoutAllResponse(
        message="All sessions have been revoked.",
        devices_revoked=devices_revoked,
    )


@router.get("/devices", response_model=DeviceListResponse)
async def list_devices(
    current_user: User = Depends(get_current_user),
):
    """List all active device sessions for the current user."""
    sessions = await get_user_sessions(str(current_user.id))
    return DeviceListResponse(
        devices=[DeviceSession(**s) for s in sessions],
        count=len(sessions),
    )


@router.delete("/devices/{device_id}", response_model=RevokeDeviceResponse)
async def revoke_device(
    device_id: str,
    current_user: User = Depends(get_current_user),
):
    """Revoke a specific device session by device ID."""
    revoked = await revoke_device_session(str(current_user.id), device_id)
    if not revoked:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Device session not found or already expired.",
        )
    return RevokeDeviceResponse(message="Device session revoked successfully.")


# ── Password reset ────────────────────────────────────────────────────────────

from pydantic import BaseModel as _BaseModel, EmailStr as _EmailStr


class ForgotPasswordRequest(_BaseModel):
    email: _EmailStr


class ForgotPasswordResponse(_BaseModel):
    message: str


class ResetPasswordRequest(_BaseModel):
    token: str
    new_password: str


class ResetPasswordResponse(_BaseModel):
    message: str


@router.post("/forgot-password", response_model=ForgotPasswordResponse)
async def forgot_password(
    request: Request,
    body: ForgotPasswordRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Send a password reset email.

    Always returns 200 regardless of whether the email exists to prevent
    user enumeration attacks.
    """
    # Rate limit: 3 requests per email per 15 minutes
    is_allowed, retry_after = await rate_limit_service.check_rate_limit(
        key=f"forgot_password:email:{body.email.lower()}",
        max_requests=3,
        window_seconds=900,
    )
    if not is_allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many password reset requests. Please try again later.",
            headers={"Retry-After": str(retry_after)},
        )

    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()

    # Always respond with success to prevent email enumeration
    if user:
        reset_token = generate_verification_token()
        await store_password_reset_token(reset_token, str(user.id))
        background_tasks.add_task(
            send_password_reset_email,
            user.email,
            user.full_name or "",
            reset_token,
        )

    return ForgotPasswordResponse(
        message="If an account with that email exists, a password reset link has been sent."
    )


@router.post("/reset-password", response_model=ResetPasswordResponse)
async def reset_password(
    body: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
):
    """Reset a user's password using a valid reset token."""
    if len(body.new_password) < 6:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Password must be at least 6 characters.",
        )

    user_id = await consume_password_reset_token(body.token)
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired password reset token.",
        )

    result = await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found.",
        )

    user.password_hash = get_password_hash(body.new_password)
    await db.commit()

    # Invalidate all existing tokens for this user
    await invalidate_user_tokens(user_id)

    # Invalidate user cache
    from app.core.cache import invalidate_user_cache
    await invalidate_user_cache(user_id)

    return ResetPasswordResponse(message="Password reset successfully.")


# ── Email verification ────────────────────────────────────────────────────────


class VerifyEmailRequest(_BaseModel):
    token: str


class VerifyEmailResponse(_BaseModel):
    message: str
    email_verified: bool


@router.post("/verify-email", response_model=VerifyEmailResponse)
async def verify_email(
    body: VerifyEmailRequest,
    db: AsyncSession = Depends(get_db),
):
    """Verify a user's email address using the token from the verification email."""
    user_id = await consume_verification_token(body.token)
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired verification token.",
        )

    result = await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found.",
        )

    if not user.email_verified:
        user.email_verified = True
        await db.commit()

    # Invalidate user cache so the updated field is picked up
    from app.core.cache import invalidate_user_cache
    await invalidate_user_cache(str(user.id))

    return VerifyEmailResponse(message="Email verified successfully.", email_verified=True)


@router.post("/resend-verification", response_model=VerifyEmailResponse)
async def resend_verification(
    request: Request,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
):
    """Resend the email verification email for the currently authenticated user."""
    # Rate limit: 3 resend attempts per user per hour
    is_allowed, retry_after = await rate_limit_service.check_rate_limit(
        key=f"resend_verify:user:{current_user.id}",
        max_requests=3,
        window_seconds=3600,
    )
    if not is_allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many verification email requests. Please try again later.",
            headers={"Retry-After": str(retry_after)},
        )

    if current_user.email_verified:
        return VerifyEmailResponse(
            message="Email is already verified.",
            email_verified=True,
        )

    verify_token_value = generate_verification_token()
    await store_verification_token(verify_token_value, str(current_user.id))
    background_tasks.add_task(
        send_verification_email,
        current_user.email,
        current_user.full_name or "",
        verify_token_value,
    )

    return VerifyEmailResponse(
        message="Verification email sent.",
        email_verified=False,
    )
