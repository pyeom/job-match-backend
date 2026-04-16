"""
WorkOS AuthKit service.
The WorkOS Python SDK is synchronous — all calls are wrapped in asyncio.to_thread().
"""
import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

from workos import WorkOSClient
from workos._errors import EmailVerificationRequiredError
from app.core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class WorkOSUser:
    id: str
    email: str
    email_verified: bool
    first_name: Optional[str]
    last_name: Optional[str]
    profile_picture_url: Optional[str]


@dataclass
class WorkOSEmailVerificationRequired:
    email: str
    email_verification_id: str
    pending_authentication_token: str


def _get_client() -> WorkOSClient:
    if not settings.workos_api_key or not settings.workos_client_id:
        raise RuntimeError(
            "WorkOS is not configured. Set WORKOS_API_KEY and WORKOS_CLIENT_ID."
        )
    return WorkOSClient(
        api_key=settings.workos_api_key,
        client_id=settings.workos_client_id,
    )


def _normalize(raw) -> WorkOSUser:
    return WorkOSUser(
        id=raw.id,
        email=raw.email,
        email_verified=getattr(raw, "email_verified", True),
        first_name=getattr(raw, "first_name", None),
        last_name=getattr(raw, "last_name", None),
        profile_picture_url=getattr(raw, "profile_picture_url", None),
    )


async def get_user_from_code(code: str) -> WorkOSUser | WorkOSEmailVerificationRequired:
    """Exchange a WorkOS authorization code for a normalized user object.

    Returns WorkOSEmailVerificationRequired when WorkOS requires the user to
    verify their email before completing sign-in (happens on first social login
    when email verification is enabled in the WorkOS dashboard).
    """
    def _exchange() -> WorkOSUser | WorkOSEmailVerificationRequired:
        client = _get_client()
        try:
            result = client.user_management.authenticate_with_code(code=code)
            return _normalize(result.user)
        except EmailVerificationRequiredError as exc:
            return WorkOSEmailVerificationRequired(
                email=exc.email or "",
                email_verification_id=exc.email_verification_id or "",
                pending_authentication_token=exc.pending_authentication_token or "",
            )

    try:
        return await asyncio.to_thread(_exchange)
    except Exception as exc:
        logger.error("WorkOS code exchange failed: %s", exc)
        raise ValueError(f"WorkOS authentication failed: {exc}") from exc


async def verify_email_and_get_user(
    code: str, pending_authentication_token: str
) -> WorkOSUser:
    """Complete sign-in after email verification."""
    def _verify() -> WorkOSUser:
        client = _get_client()
        result = client.user_management.authenticate_with_email_verification(
            code=code,
            pending_authentication_token=pending_authentication_token,
        )
        return _normalize(result.user)

    try:
        return await asyncio.to_thread(_verify)
    except Exception as exc:
        logger.error("WorkOS email verification failed: %s", exc)
        raise ValueError(f"Email verification failed: {exc}") from exc
