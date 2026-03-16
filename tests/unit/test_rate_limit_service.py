"""
Unit tests for RateLimitService — Redis-unavailable behaviour (H1).

Verifies that when Redis is unreachable the service fails closed in
production (returns False) and fails open in dev/test (returns True).
"""

from __future__ import annotations

import pytest

from app.services.rate_limit_service import RateLimitService


async def _raise_redis_error():
    raise ConnectionError("Redis unavailable")


# ---------------------------------------------------------------------------
# Redis-unavailable: production must fail closed
# ---------------------------------------------------------------------------
class TestRedisUnavailable:
    async def test_production_fails_closed(self, monkeypatch):
        """When Redis raises, production mode must return (False, 60)."""
        monkeypatch.setattr("app.core.cache.get_redis", _raise_redis_error)

        from app.core.config import settings
        monkeypatch.setattr(settings, "app_env", "production")

        service = RateLimitService()
        allowed, retry_after = await service.check_rate_limit(
            "login:ip:1.2.3.4", max_requests=5, window_seconds=60
        )

        assert allowed is False
        assert retry_after == 60

    async def test_dev_fails_open(self, monkeypatch):
        """When Redis raises, dev mode must return (True, 0)."""
        monkeypatch.setattr("app.core.cache.get_redis", _raise_redis_error)

        from app.core.config import settings
        monkeypatch.setattr(settings, "app_env", "dev")

        service = RateLimitService()
        allowed, retry_after = await service.check_rate_limit(
            "login:ip:1.2.3.4", max_requests=5, window_seconds=60
        )

        assert allowed is True
        assert retry_after == 0

    async def test_test_env_fails_open(self, monkeypatch):
        """When Redis raises, test env must also fail open."""
        monkeypatch.setattr("app.core.cache.get_redis", _raise_redis_error)

        from app.core.config import settings
        monkeypatch.setattr(settings, "app_env", "test")

        service = RateLimitService()
        allowed, retry_after = await service.check_rate_limit(
            "login:email:user@example.com", max_requests=10, window_seconds=300
        )

        assert allowed is True
        assert retry_after == 0
