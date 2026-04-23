import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db

logger = logging.getLogger(__name__)
from app.core.security import (
    verify_password, get_password_hash,
    create_access_token, create_refresh_token,
    verify_token, blacklist_token, is_token_expired, get_token_expiration,
    invalidate_user_tokens,
    get_device_id_from_token, get_token_expires_at, _get_token_hash,
    store_device_session, update_device_session, revoke_device_session,
    revoke_all_user_sessions, get_user_sessions,
)
from app.models.user import User, UserRole, CompanyRole
from app.models.company import Company
from app.models.pipeline import PipelineTemplate, DEFAULT_PIPELINE_STAGES
from app.schemas.auth import (
    UserCreate, CompanyUserCreate, UserLogin, Token, LogoutResponse,
    RefreshTokenRequest, TokenRefreshResponse, RefreshTokenLogout,
    DeviceSession, DeviceListResponse, LogoutAllResponse, RevokeDeviceResponse,
    WorkOSCallbackRequest,
    WorkOSEmailVerifyRequest,
    WorkOSEmailVerificationPending,
)
from app.services.workos_service import (
    get_user_from_code,
    verify_email_and_get_user,
    WorkOSEmailVerificationRequired,
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
from app.core.config import settings, parse_rate_limit

router = APIRouter()


@router.post("/register", response_model=Token)
async def register(
    request: Request,
    user_data: UserCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Register a new job seeker user"""
    # Rate limit: configurable via settings.rate_limit_register (default 10/hour)
    _rl_reg_max, _rl_reg_window = parse_rate_limit(settings.rate_limit_register)
    client_ip = request.client.host if request.client else "unknown"
    is_allowed, retry_after = await rate_limit_service.check_rate_limit(
        key=f"register:ip:{client_ip}",
        max_requests=_rl_reg_max,
        window_seconds=_rl_reg_window,
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
        logger.error("Failed to generate profile embedding for user %s", db_user.id, exc_info=True)

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

    access_token = create_access_token(data={
        "sub": str(db_user.id),
        "role": db_user.role.value,
        "tenant_id": None,
        "puc_complete": False,
    })
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
    # Rate limit: configurable via settings.rate_limit_register (shared bucket with /register)
    _rl_reg_max, _rl_reg_window = parse_rate_limit(settings.rate_limit_register)
    client_ip = request.client.host if request.client else "unknown"
    is_allowed, retry_after = await rate_limit_service.check_rate_limit(
        key=f"register:ip:{client_ip}",
        max_requests=_rl_reg_max,
        window_seconds=_rl_reg_window,
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

    is_new_company = False
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
        is_new_company = True

        # Seed default pipeline template for the new company
        default_template = PipelineTemplate(
            id=uuid.uuid4(),
            company_id=company_id,
            name="Default Pipeline",
            stages=DEFAULT_PIPELINE_STAGES,
            is_default=True,
        )
        db.add(default_template)

    # First user of a new company gets ADMIN company role; additional users get RECRUITER
    resolved_company_role = CompanyRole.ADMIN if is_new_company else CompanyRole.RECRUITER

    # Create new company user (email_verified defaults to False)
    hashed_password = get_password_hash(user_data.password)
    db_user = User(
        id=uuid.uuid4(),
        email=user_data.email,
        password_hash=hashed_password,
        full_name=user_data.full_name,
        role=user_data.role,
        company_id=company_id,
        company_role=resolved_company_role,
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
        logger.error("Failed to generate profile embedding for user %s", db_user.id, exc_info=True)

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

    access_token = create_access_token(data={
        "sub": str(db_user.id),
        "role": db_user.role.value,
        "tenant_id": str(company_id),
        "puc_complete": False,
    })
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


@router.post("/workos/callback", response_model=Token, responses={202: {"model": WorkOSEmailVerificationPending}})
async def workos_callback(
    request: Request,
    body: WorkOSCallbackRequest,
    db: AsyncSession = Depends(get_db),
):
    """Exchange a WorkOS authorization code for an internal JWT.

    Returns 202 with email_verification_required when WorkOS needs the user
    to verify their email. The frontend should show a verification code input
    and POST to /workos/verify-email with the code + pending_authentication_token.
    """
    client_ip = request.client.host if request.client else "unknown"
    is_allowed, retry_after = await rate_limit_service.check_rate_limit(
        key=f"workos_callback:ip:{client_ip}",
        max_requests=20,
        window_seconds=900,
    )
    if not is_allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts. Please try again later.",
            headers={"Retry-After": str(retry_after)},
        )

    try:
        result = await get_user_from_code(body.code)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc))

    if isinstance(result, WorkOSEmailVerificationRequired):
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=202,
            content=WorkOSEmailVerificationPending(
                email=result.email,
                email_verification_id=result.email_verification_id,
                pending_authentication_token=result.pending_authentication_token,
            ).model_dump(),
        )

    workos_user = result

    # Upsert: external_id match → email match → create new
    db_user = None
    is_new_user = False

    result = await db.execute(select(User).where(User.external_id == workos_user.id))
    db_user = result.scalar_one_or_none()

    if db_user is None:
        result = await db.execute(select(User).where(User.email == workos_user.email))
        db_user = result.scalar_one_or_none()
        if db_user is not None:
            db_user.auth_provider = "workos"
            db_user.external_id = workos_user.id
            db_user.email_verified = True
            if workos_user.profile_picture_url and not db_user.avatar_url:
                db_user.avatar_url = workos_user.profile_picture_url

    if db_user is None:
        is_new_user = True
        role_str = (body.role or "job_seeker").lower()
        if role_str in ("company_admin", "admin"):
            resolved_role = UserRole.COMPANY_ADMIN
        elif role_str in ("company_recruiter", "recruiter"):
            resolved_role = UserRole.COMPANY_RECRUITER
        else:
            resolved_role = UserRole.JOB_SEEKER

        client_app = request.headers.get("X-Client-App", "").lower()
        if client_app == "jobseeker" and resolved_role in (
            UserRole.COMPANY_RECRUITER, UserRole.COMPANY_ADMIN,
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect email or password",
                headers={"WWW-Authenticate": "Bearer"},
            )

        full_name = " ".join(
            filter(None, [workos_user.first_name, workos_user.last_name])
        ) or workos_user.email.split("@")[0]

        db_user = User(
            id=uuid.uuid4(),
            email=workos_user.email,
            password_hash=None,
            auth_provider="workos",
            external_id=workos_user.id,
            full_name=full_name,
            avatar_url=workos_user.profile_picture_url,
            role=resolved_role,
            email_verified=True,
        )
        db.add(db_user)
        await db.flush()

        try:
            profile_embedding = embedding_service.generate_user_embedding(
                headline=db_user.headline,
                skills=db_user.skills,
                preferences=db_user.preferred_locations,
            )
            db_user.profile_embedding = profile_embedding
        except Exception as e:
            pass

        if resolved_role in (UserRole.COMPANY_ADMIN, UserRole.COMPANY_RECRUITER):
            if not body.company_name:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="company_name is required when registering a company user.",
                )
            result = await db.execute(select(Company).where(Company.name == body.company_name))
            db_company = result.scalar_one_or_none()
            is_new_company = db_company is None
            if not db_company:
                db_company = Company(
                    id=uuid.uuid4(),
                    name=body.company_name,
                    description=body.company_description,
                    website=body.company_website,
                    industry=body.company_industry,
                    size=body.company_size,
                    location=body.company_location,
                )
                db.add(db_company)
                await db.flush()
                default_template = PipelineTemplate(
                    id=uuid.uuid4(),
                    company_id=db_company.id,
                    name="Default Pipeline",
                    stages=DEFAULT_PIPELINE_STAGES,
                    is_default=True,
                )
                db.add(default_template)
            db_user.company_id = db_company.id
            db_user.company_role = CompanyRole.ADMIN if is_new_company else CompanyRole.RECRUITER
    else:
        client_app = request.headers.get("X-Client-App", "").lower()
        if client_app == "jobseeker" and db_user.role in (
            UserRole.COMPANY_RECRUITER, UserRole.COMPANY_ADMIN,
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect email or password",
                headers={"WWW-Authenticate": "Bearer"},
            )

    await db.commit()
    await db.refresh(db_user)

    puc_complete = False
    if db_user.role == UserRole.JOB_SEEKER:
        try:
            from app.repositories.puc_repository import PUCRepository
            puc_repo = PUCRepository(db)
            profile = await puc_repo.get_by_user_id(db_user.id)
            puc_complete = (
                profile is not None and (profile.completeness_score or 0.0) >= 1.0
            )
        except Exception:
            logger.warning("Failed to fetch PUC profile for token payload, defaulting to incomplete", exc_info=True)

    token_data: dict = {
        "sub": str(db_user.id),
        "role": db_user.role.value,
        "tenant_id": str(db_user.company_id) if db_user.company_id else None,
        "puc_complete": puc_complete,
    }

    device_id = str(uuid.uuid4())
    device_name = body.device_name or "Unknown Device"
    platform_name = body.platform or "unknown"

    access_token = create_access_token(data=token_data)
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
        "is_new_user": is_new_user,
    }


@router.post("/workos/verify-email", response_model=Token)
async def workos_verify_email(
    request: Request,
    body: WorkOSEmailVerifyRequest,
    db: AsyncSession = Depends(get_db),
):
    """Complete WorkOS social login after email verification."""
    client_ip = request.client.host if request.client else "unknown"
    is_allowed, retry_after = await rate_limit_service.check_rate_limit(
        key=f"workos_callback:ip:{client_ip}",
        max_requests=20,
        window_seconds=900,
    )
    if not is_allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts. Please try again later.",
            headers={"Retry-After": str(retry_after)},
        )

    try:
        workos_user = await verify_email_and_get_user(body.code, body.pending_authentication_token)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc))

    result = await db.execute(select(User).where(User.external_id == workos_user.id))
    db_user = result.scalar_one_or_none()
    is_new_user = False

    if db_user is None:
        result = await db.execute(select(User).where(User.email == workos_user.email))
        db_user = result.scalar_one_or_none()
        if db_user is not None:
            db_user.auth_provider = "workos"
            db_user.external_id = workos_user.id
            db_user.email_verified = True

    if db_user is None:
        is_new_user = True
        role_str = (body.role or "job_seeker").lower()
        resolved_role = UserRole.JOB_SEEKER
        if role_str in ("company_admin", "admin"):
            resolved_role = UserRole.COMPANY_ADMIN
        elif role_str in ("company_recruiter", "recruiter"):
            resolved_role = UserRole.COMPANY_RECRUITER

        full_name = " ".join(
            filter(None, [workos_user.first_name, workos_user.last_name])
        ) or workos_user.email.split("@")[0]

        db_user = User(
            id=uuid.uuid4(),
            email=workos_user.email,
            password_hash=None,
            auth_provider="workos",
            external_id=workos_user.id,
            full_name=full_name,
            avatar_url=workos_user.profile_picture_url,
            role=resolved_role,
            email_verified=True,
        )
        db.add(db_user)
        await db.flush()

    await db.commit()
    await db.refresh(db_user)

    puc_complete = False
    if db_user.role == UserRole.JOB_SEEKER:
        try:
            from app.repositories.puc_repository import PUCRepository
            puc_repo = PUCRepository(db)
            profile = await puc_repo.get_by_user_id(db_user.id)
            puc_complete = profile is not None and (profile.completeness_score or 0.0) >= 1.0
        except Exception:
            logger.warning("Failed to fetch PUC profile for token payload, defaulting to incomplete", exc_info=True)

    token_data: dict = {
        "sub": str(db_user.id),
        "role": db_user.role.value,
        "tenant_id": str(db_user.company_id) if db_user.company_id else None,
        "puc_complete": puc_complete,
    }

    device_id = str(uuid.uuid4())
    access_token = create_access_token(data=token_data)
    refresh_token = create_refresh_token(data={"sub": str(db_user.id), "did": device_id})

    token_hash = _get_token_hash(refresh_token)
    expires_at = get_token_expires_at(refresh_token)
    await store_device_session(
        str(db_user.id), device_id, token_hash, expires_at,
        body.device_name or "Unknown Device",
        body.platform or "unknown",
    )

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": settings.access_token_expires,
        "is_new_user": is_new_user,
    }


@router.post("/login", response_model=Token)
async def login(
    request: Request,
    user_credentials: UserLogin,
    db: AsyncSession = Depends(get_db),
):
    """Authenticate user and return tokens"""
    _rl_email_max, _rl_email_window = parse_rate_limit(settings.rate_limit_login_email)
    _rl_ip_max, _rl_ip_window = parse_rate_limit(settings.rate_limit_login_ip)
    client_ip = request.client.host if request.client else "unknown"
    email_key = f"login:email:{user_credentials.email.lower()}"
    ip_key = f"login:ip:{client_ip}"

    # Check limits before attempting auth (peek — does not increment)
    is_allowed, retry_after = await rate_limit_service.peek_rate_limit(
        key=email_key,
        max_requests=_rl_email_max,
        window_seconds=_rl_email_window,
    )
    if not is_allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts for this account. Please try again later.",
            headers={"Retry-After": str(retry_after)},
        )

    is_allowed, retry_after = await rate_limit_service.peek_rate_limit(
        key=ip_key,
        max_requests=_rl_ip_max,
        window_seconds=_rl_ip_window,
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

    # Block WorkOS-only accounts from password login
    if user and user.auth_provider == "workos" and not user.password_hash:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "This account uses social sign-in. "
                "Please sign in with the social provider you used to register."
            ),
        )

    password_valid = user and verify_password(user_credentials.password, user.password_hash)

    if not user or not password_valid:
        # Only failed attempts count toward the limit
        await rate_limit_service.record_attempt(email_key, _rl_email_window)
        await rate_limit_service.record_attempt(ip_key, _rl_ip_window)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Reject company accounts from the job-seeker app.
    # The header X-Client-App: jobseeker is sent by the job-seeker frontend on
    # every request. Company users must authenticate through the company portal
    # (<company>.job-match.cl), not through this app.
    client_app = request.headers.get("X-Client-App", "").lower()
    if client_app == "jobseeker" and user.role in (
        UserRole.COMPANY_RECRUITER,
        UserRole.COMPANY_ADMIN,
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Create tokens with device session tracking
    device_id = str(uuid.uuid4())
    device_name = user_credentials.device_name or "Unknown Device"
    platform_name = user_credentials.platform or "unknown"

    token_data: dict = {
        "sub": str(user.id),
        "role": user.role.value,
        "tenant_id": str(user.company_id) if user.company_id else None,
        "puc_complete": False,
    }

    access_token = create_access_token(data=token_data)
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

    access_token_data: dict = {
        "sub": str(user.id),
        "role": user.role.value,
        "tenant_id": str(user.company_id) if user.company_id else None,
        "puc_complete": False,
    }

    access_token = create_access_token(data=access_token_data)
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
