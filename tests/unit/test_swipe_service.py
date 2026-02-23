"""
Unit tests for SwipeService.

All database I/O is replaced with AsyncMock objects so tests run without a
real database.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.models.swipe import Swipe
from app.models.user import User, UserRole
from app.services.swipe_service import SwipeService


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------
def _make_user(user_id: uuid.UUID | None = None) -> User:
    user = User()
    user.id = user_id or uuid.uuid4()
    user.email = "test@example.com"
    user.role = UserRole.JOB_SEEKER
    return user


def _make_swipe(
    user_id: uuid.UUID | None = None,
    direction: str = "RIGHT",
    is_undone: bool = False,
    seconds_old: int = 0,
) -> Swipe:
    swipe = Swipe()
    swipe.id = uuid.uuid4()
    swipe.user_id = user_id or uuid.uuid4()
    swipe.job_id = uuid.uuid4()
    swipe.direction = direction
    swipe.is_undone = is_undone
    swipe.undone_at = None
    swipe.created_at = datetime.now(timezone.utc) - timedelta(seconds=seconds_old)
    return swipe


def _make_service(
    mock_swipe: Swipe | None = None,
    mark_as_undone_return: Swipe | None = None,
) -> tuple[SwipeService, MagicMock]:
    repo = MagicMock()
    repo.get = AsyncMock(return_value=mock_swipe)
    repo.mark_as_undone = AsyncMock(
        return_value=mark_as_undone_return or mock_swipe
    )
    repo.get_last_swipe = AsyncMock(return_value=mock_swipe)
    return SwipeService(swipe_repo=repo), repo


# ---------------------------------------------------------------------------
# check_undo_eligibility
# ---------------------------------------------------------------------------
class TestCheckUndoEligibility:
    @pytest.mark.asyncio
    async def test_valid_within_window(self):
        user = _make_user()
        swipe = _make_swipe(user_id=user.id, seconds_old=1)
        service, _ = _make_service()
        db = AsyncMock()

        can_undo, error = await service.check_undo_eligibility(db, user, swipe)
        assert can_undo is True
        assert error is None

    @pytest.mark.asyncio
    async def test_wrong_owner_denied(self):
        user = _make_user()
        # swipe belongs to a *different* user
        swipe = _make_swipe(user_id=uuid.uuid4(), seconds_old=1)
        service, _ = _make_service()
        db = AsyncMock()

        can_undo, error = await service.check_undo_eligibility(db, user, swipe)
        assert can_undo is False
        assert "does not belong" in error

    @pytest.mark.asyncio
    async def test_already_undone_denied(self):
        user = _make_user()
        swipe = _make_swipe(user_id=user.id, is_undone=True, seconds_old=1)
        service, _ = _make_service()
        db = AsyncMock()

        can_undo, error = await service.check_undo_eligibility(db, user, swipe)
        assert can_undo is False
        assert "already been undone" in error

    @pytest.mark.asyncio
    async def test_outside_undo_window_denied(self):
        user = _make_user()
        swipe = _make_swipe(user_id=user.id, seconds_old=10)  # 10s > 5s window
        service, _ = _make_service()
        db = AsyncMock()

        can_undo, error = await service.check_undo_eligibility(db, user, swipe)
        assert can_undo is False
        assert "expired" in error

    @pytest.mark.asyncio
    async def test_exactly_at_boundary_denied(self):
        user = _make_user()
        # Created exactly at the window edge
        swipe = _make_swipe(user_id=user.id, seconds_old=SwipeService.UNDO_WINDOW_SECONDS + 1)
        service, _ = _make_service()
        db = AsyncMock()

        can_undo, error = await service.check_undo_eligibility(db, user, swipe)
        assert can_undo is False


# ---------------------------------------------------------------------------
# undo_swipe
# ---------------------------------------------------------------------------
class TestUndoSwipe:
    @pytest.mark.asyncio
    async def test_undo_within_window_succeeds(self):
        user = _make_user()
        swipe = _make_swipe(user_id=user.id, direction="LEFT", seconds_old=1)
        undone_swipe = _make_swipe(user_id=user.id, direction="LEFT", seconds_old=1)
        undone_swipe.is_undone = True
        undone_swipe.undone_at = datetime.now(timezone.utc)

        service, repo = _make_service(mock_swipe=swipe, mark_as_undone_return=undone_swipe)
        db = AsyncMock()
        db.execute = AsyncMock()

        result = await service.undo_swipe(db, user, swipe.id)
        repo.mark_as_undone.assert_called_once_with(db, swipe)
        assert result is undone_swipe

    @pytest.mark.asyncio
    async def test_undo_right_swipe_deletes_application(self):
        user = _make_user()
        swipe = _make_swipe(user_id=user.id, direction="RIGHT", seconds_old=1)
        undone_swipe = _make_swipe(user_id=user.id, direction="RIGHT", seconds_old=1)
        undone_swipe.is_undone = True
        undone_swipe.direction = "RIGHT"
        undone_swipe.undone_at = datetime.now(timezone.utc)

        service, repo = _make_service(mock_swipe=swipe, mark_as_undone_return=undone_swipe)
        db = AsyncMock()
        db.execute = AsyncMock()

        await service.undo_swipe(db, user, swipe.id)
        # db.execute should be called to delete the application
        db.execute.assert_called()

    @pytest.mark.asyncio
    async def test_swipe_not_found_raises_404(self):
        user = _make_user()
        service, _ = _make_service(mock_swipe=None)  # repo.get returns None
        db = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await service.undo_swipe(db, user, uuid.uuid4())
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_undo_outside_window_raises_400(self):
        user = _make_user()
        swipe = _make_swipe(user_id=user.id, direction="LEFT", seconds_old=60)
        service, _ = _make_service(mock_swipe=swipe)
        db = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await service.undo_swipe(db, user, swipe.id)
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_undo_wrong_owner_raises_400(self):
        user = _make_user()
        other_user_swipe = _make_swipe(user_id=uuid.uuid4(), direction="LEFT", seconds_old=1)
        service, _ = _make_service(mock_swipe=other_user_swipe)
        db = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await service.undo_swipe(db, user, other_user_swipe.id)
        assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# get_last_swipe_with_window
# ---------------------------------------------------------------------------
class TestGetLastSwipeWithWindow:
    @pytest.mark.asyncio
    async def test_returns_swipe_and_remaining_time_within_window(self):
        user = _make_user()
        swipe = _make_swipe(user_id=user.id, seconds_old=2)
        service, repo = _make_service(mock_swipe=swipe)
        db = AsyncMock()

        result = await service.get_last_swipe_with_window(db, user)
        assert result is not None
        returned_swipe, remaining = result
        assert returned_swipe is swipe
        assert remaining >= 0
        assert remaining <= SwipeService.UNDO_WINDOW_SECONDS

    @pytest.mark.asyncio
    async def test_returns_none_when_no_swipe(self):
        user = _make_user()
        service, repo = _make_service(mock_swipe=None)
        repo.get_last_swipe = AsyncMock(return_value=None)
        db = AsyncMock()

        result = await service.get_last_swipe_with_window(db, user)
        assert result is None

    @pytest.mark.asyncio
    async def test_remaining_time_decreases_with_age(self):
        user = _make_user()
        # 1 second old — should have ~4 seconds remaining
        swipe = _make_swipe(user_id=user.id, seconds_old=1)
        service, _ = _make_service(mock_swipe=swipe)
        db = AsyncMock()

        result = await service.get_last_swipe_with_window(db, user)
        assert result is not None
        _, remaining = result
        assert remaining <= SwipeService.UNDO_WINDOW_SECONDS - 1
