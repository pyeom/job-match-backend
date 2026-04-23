"""
Unit tests for the WorkOS AuthKit service layer.

Covers:
  app/services/workos_service.py
    - get_user_from_code() success path
    - get_user_from_code() email-verification-required path
    - get_user_from_code() propagates SDK errors as ValueError
    - _get_client() raises RuntimeError when settings are absent
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_raw_user(
    id: str = "workos_user_01ABC",
    email: str = "unit@example.com",
    email_verified: bool = True,
    first_name: str = "Unit",
    last_name: str = "Test",
    profile_picture_url: str | None = None,
) -> MagicMock:
    """Return a mock that looks like the object WorkOS SDK returns as result.user."""
    raw = MagicMock()
    raw.id = id
    raw.email = email
    raw.email_verified = email_verified
    raw.first_name = first_name
    raw.last_name = last_name
    raw.profile_picture_url = profile_picture_url
    return raw


def _make_auth_result(user_mock: MagicMock) -> MagicMock:
    """Wrap a raw user mock in a result object (result.user)."""
    result = MagicMock()
    result.user = user_mock
    return result


# ---------------------------------------------------------------------------
# Test: successful code exchange
# ---------------------------------------------------------------------------
class TestGetUserFromCodeSuccess:
    @pytest.mark.asyncio
    async def test_get_user_from_code_success(self):
        """authenticate_with_code returns a user object → WorkOSUser with correct fields."""
        raw_user = _make_raw_user(
            id="workos_user_01ABC",
            email="unit@example.com",
            email_verified=True,
            first_name="Unit",
            last_name="Test",
            profile_picture_url="https://cdn.example.com/avatar.png",
        )

        mock_client = MagicMock()
        mock_client.user_management.authenticate_with_code.return_value = (
            _make_auth_result(raw_user)
        )

        with patch(
            "app.services.workos_service._get_client",
            return_value=mock_client,
        ):
            from app.services.workos_service import WorkOSUser, get_user_from_code

            result = await get_user_from_code("valid_code")

        assert isinstance(result, WorkOSUser)
        assert result.id == "workos_user_01ABC"
        assert result.email == "unit@example.com"
        assert result.email_verified is True
        assert result.first_name == "Unit"
        assert result.last_name == "Test"
        assert result.profile_picture_url == "https://cdn.example.com/avatar.png"


# ---------------------------------------------------------------------------
# Test: email-verification-required path
# ---------------------------------------------------------------------------
class TestGetUserFromCodeEmailVerificationRequired:
    @pytest.mark.asyncio
    async def test_get_user_from_code_email_verification_required(self):
        """authenticate_with_code raises EmailVerificationRequiredError → WorkOSEmailVerificationRequired."""
        from workos._errors import EmailVerificationRequiredError

        exc = EmailVerificationRequiredError(
            email="verify@example.com",
            email_verification_id="evid_01XYZ",
        )
        exc.pending_authentication_token = "pat_01ABC"

        mock_client = MagicMock()
        mock_client.user_management.authenticate_with_code.side_effect = exc

        with patch(
            "app.services.workos_service._get_client",
            return_value=mock_client,
        ):
            from app.services.workos_service import (
                WorkOSEmailVerificationRequired,
                get_user_from_code,
            )

            result = await get_user_from_code("code_needing_verify")

        assert isinstance(result, WorkOSEmailVerificationRequired)
        assert result.email == "verify@example.com"
        assert result.email_verification_id == "evid_01XYZ"
        assert result.pending_authentication_token == "pat_01ABC"


# ---------------------------------------------------------------------------
# Test: generic SDK error propagates as ValueError
# ---------------------------------------------------------------------------
class TestGetUserFromCodeSdkError:
    @pytest.mark.asyncio
    async def test_get_user_from_code_raises_on_sdk_error(self):
        """A generic RuntimeError from the SDK is wrapped and re-raised as ValueError."""
        mock_client = MagicMock()
        mock_client.user_management.authenticate_with_code.side_effect = RuntimeError(
            "network timeout"
        )

        with patch(
            "app.services.workos_service._get_client",
            return_value=mock_client,
        ):
            from app.services.workos_service import get_user_from_code

            with pytest.raises(ValueError, match="WorkOS authentication failed"):
                await get_user_from_code("bad_code")


# ---------------------------------------------------------------------------
# Test: unconfigured WorkOS (no API key / client ID)
# ---------------------------------------------------------------------------
class TestGetClientNotConfigured:
    @pytest.mark.asyncio
    async def test_raises_if_not_configured(self, monkeypatch):
        """When workos_api_key is None, _get_client raises RuntimeError which surfaces as ValueError."""
        from app.core.config import settings

        monkeypatch.setattr(settings, "workos_api_key", None, raising=False)

        # Import fresh so we call the real _get_client (which reads settings directly)
        from app.services.workos_service import get_user_from_code

        with pytest.raises(ValueError):
            await get_user_from_code("x")
