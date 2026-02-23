"""
Top-level pytest configuration.

Provides:
  - A test SQLite database (aiosqlite) with all tables created fresh per session.
  - A db_session fixture that rolls back each test in a transaction.
  - An async_client fixture wired to the FastAPI app with all heavy external
    dependencies (Redis, embedding model, Elasticsearch, ARQ) mocked out.
  - Convenience auth token fixtures for a job-seeker and a company admin.
"""

from __future__ import annotations

import os
import uuid
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

# ---------------------------------------------------------------------------
# Environment must be set BEFORE any app module is imported so that
# pydantic-settings picks up the test values.
# ---------------------------------------------------------------------------
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_USER", "test")
os.environ.setdefault("POSTGRES_PASSWORD", "test")
os.environ.setdefault("POSTGRES_DB", "test")
os.environ.setdefault("JWT_SECRET", "test-secret-key-that-is-long-enough-32c")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")
os.environ.setdefault("ELASTICSEARCH_URL", "http://localhost:9200")

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import JSON, event
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

# ---------------------------------------------------------------------------
# SQLite in-memory URL for testing.
# pgvector is installed in the container and its Vector column type works with
# SQLite's DDL generation, so no stubbing is needed.
# ---------------------------------------------------------------------------
TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "sqlite+aiosqlite:///:memory:",
)

# ---------------------------------------------------------------------------
# Shared zero-vector for ML embedding mocks (384 dims = all-MiniLM-L6-v2)
# ---------------------------------------------------------------------------
ZERO_EMBEDDING: list[float] = [0.0] * 384


def _patch_postgres_types_for_sqlite(metadata) -> None:
    """
    Replace PostgreSQL-specific column types that SQLite cannot compile.

    SQLAlchemy's UUID(as_uuid=True) and JSON both render fine on SQLite, but
    JSONB (from sqlalchemy.dialects.postgresql) does not.  Walk the metadata
    before DDL generation and swap any JSONB column for a plain JSON column.
    """
    from sqlalchemy.dialects.postgresql import JSONB

    for table in metadata.tables.values():
        for col in table.columns:
            if isinstance(col.type, JSONB):
                col.type = JSON()


# ---------------------------------------------------------------------------
# Session-scoped test engine (SQLite in-memory, shared via StaticPool so all
# connections see the same data within a test process).
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture(scope="session")
async def engine():
    """Create the SQLite test engine and all tables once per test session."""
    # Import Base here (after env vars are set) to ensure models register.
    from app.core.database import Base

    # Force all model modules to load so their tables register on Base.metadata
    import app.models.user          # noqa: F401
    import app.models.company       # noqa: F401
    import app.models.job           # noqa: F401
    import app.models.swipe         # noqa: F401
    import app.models.application   # noqa: F401
    import app.models.notification  # noqa: F401
    import app.models.push_token    # noqa: F401
    import app.models.document      # noqa: F401
    import app.models.filter_preset # noqa: F401
    import app.models.recent_search # noqa: F401
    import app.models.interaction   # noqa: F401

    # Swap JSONB → JSON so SQLite can render the DDL
    _patch_postgres_types_for_sqlite(Base.metadata)

    test_engine = create_async_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield test_engine
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await test_engine.dispose()


# ---------------------------------------------------------------------------
# Per-test DB session that rolls back after each test for isolation.
#
# Strategy: wrap each test in a single outer transaction that is rolled back.
# - The outer connection begins a real transaction.
# - A custom NonCommittingSession is used: commit() is overridden to only
#   flush, so endpoint code that calls session.commit() never actually
#   commits to the database — all writes stay within the outer transaction.
# - At teardown the outer transaction is rolled back, erasing all writes.
#
# This is necessary because SQLite does not properly handle nested
# SAVEPOINT transactions the way PostgreSQL does: calling session.commit()
# in join_transaction_mode="create_savepoint" escalates to a real commit
# in aiosqlite, defeating per-test isolation.
# ---------------------------------------------------------------------------
class _NonCommittingSession(AsyncSession):
    """AsyncSession subclass where commit() becomes flush().

    Endpoint handlers call ``await db.commit()`` after writes.  In the
    test suite we want those writes to be visible within the request
    (so subsequent reads in the same request work), but we do NOT want
    them persisted across tests.  By turning commit() into flush() we
    keep the data in the open outer transaction, which gets rolled back
    in fixture teardown.
    """

    async def commit(self) -> None:  # type: ignore[override]
        await self.flush()


@pytest_asyncio.fixture
async def db_session(engine) -> AsyncGenerator[AsyncSession, None]:
    """Provide a per-test database session that is fully rolled back on teardown."""
    # Acquire a raw connection and start an outer transaction that we own.
    async with engine.connect() as conn:
        await conn.begin()  # outer real transaction

        # Bind a non-committing session to this connection.
        session = _NonCommittingSession(
            bind=conn,
            expire_on_commit=False,
        )

        try:
            yield session
        finally:
            await session.close()
            await conn.rollback()  # roll back the outer transaction, erasing all writes


# ---------------------------------------------------------------------------
# Redis mock — uses fakeredis so all Redis-dependent code works without a
# real Redis server.
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def mock_redis(monkeypatch):
    """Replace the Redis pool/client with an in-process fakeredis instance."""
    try:
        import fakeredis.aioredis as fakeredis_async

        fake_server = fakeredis_async.FakeServer()
        fake_redis = fakeredis_async.FakeRedis(server=fake_server, decode_responses=True)

        async def _get_redis():
            return fake_redis

        monkeypatch.setattr("app.core.cache.get_redis", _get_redis)
        # Patch the reference used directly inside security.py functions
        try:
            import app.core.security as sec_mod
            monkeypatch.setattr(sec_mod, "get_redis", _get_redis, raising=False)
        except Exception:
            pass

    except ImportError:
        # fakeredis not available — build a minimal AsyncMock fallback
        fake_redis = _build_redis_mock()

        async def _get_redis():
            return fake_redis

        monkeypatch.setattr("app.core.cache.get_redis", _get_redis)


def _build_redis_mock() -> AsyncMock:
    """Build a minimal async Redis mock used when fakeredis is unavailable."""
    fake_redis = AsyncMock()
    fake_redis.get = AsyncMock(return_value=None)
    fake_redis.set = AsyncMock(return_value=True)
    fake_redis.setex = AsyncMock(return_value=True)
    fake_redis.delete = AsyncMock(return_value=1)
    fake_redis.exists = AsyncMock(return_value=0)
    fake_redis.ping = AsyncMock(return_value=True)
    fake_redis.zrange = AsyncMock(return_value=[])

    pipeline_mock = AsyncMock()
    pipeline_mock.__aenter__ = AsyncMock(return_value=pipeline_mock)
    pipeline_mock.__aexit__ = AsyncMock(return_value=False)
    pipeline_mock.execute = AsyncMock(return_value=[0, 1, 1, True])
    pipeline_mock.zremrangebyscore = MagicMock(return_value=pipeline_mock)
    pipeline_mock.zadd = MagicMock(return_value=pipeline_mock)
    pipeline_mock.zcard = MagicMock(return_value=pipeline_mock)
    pipeline_mock.expire = MagicMock(return_value=pipeline_mock)
    fake_redis.pipeline = MagicMock(return_value=pipeline_mock)
    return fake_redis


# ---------------------------------------------------------------------------
# Embedding service mock — returns zero vectors, avoids loading the 100 MB model.
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def mock_embedding_service(monkeypatch):
    """Patch EmbeddingService so it never tries to load the sentence-transformer."""
    from app.services import embedding_service as emb_module

    # Provide a fake model so the is_loaded property is True and the guard
    # in generate_user_embedding doesn't fall through to _load_model().
    monkeypatch.setattr(emb_module.embedding_service, "_model", MagicMock())
    monkeypatch.setattr(emb_module.embedding_service, "_load_attempted", True)

    def _fake_generate_job(*args, **kwargs) -> list[float]:
        return ZERO_EMBEDDING

    async def _fake_generate_job_async(*args, **kwargs) -> list[float]:
        return ZERO_EMBEDDING

    def _fake_generate_user(*args, **kwargs) -> list[float]:
        return ZERO_EMBEDDING

    def _fake_similarity(emb1, emb2) -> float:
        return 0.85

    monkeypatch.setattr(
        emb_module.embedding_service,
        "generate_job_embedding_from_parts",
        _fake_generate_job,
    )
    monkeypatch.setattr(
        emb_module.embedding_service,
        "generate_job_embedding",
        _fake_generate_job_async,
    )
    monkeypatch.setattr(
        emb_module.embedding_service,
        "generate_user_embedding",
        _fake_generate_user,
    )
    monkeypatch.setattr(
        emb_module.embedding_service,
        "calculate_similarity",
        _fake_similarity,
    )


# ---------------------------------------------------------------------------
# Elasticsearch mock — no real ES cluster needed in tests.
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def mock_elasticsearch(monkeypatch):
    """Stub out Elasticsearch service so tests don't need a running cluster."""
    try:
        from app.services import elasticsearch_service as es_module

        fake_es = AsyncMock()
        fake_es.ensure_index = AsyncMock(return_value=False)
        fake_es.knn_discover = AsyncMock(return_value=[])
        fake_es.index_job = AsyncMock()
        fake_es.delete_job = AsyncMock()
        fake_es.close = AsyncMock()
        # Stub out the raw client used in the readiness probe
        fake_es.client = AsyncMock()
        fake_es.client.cluster = AsyncMock()
        fake_es.client.cluster.health = AsyncMock(return_value={"status": "green"})

        monkeypatch.setattr(es_module, "elasticsearch_service", fake_es)
    except (ImportError, AttributeError):
        pass


# ---------------------------------------------------------------------------
# ARQ task queue mock — prevents tests from trying to reach Redis for job queuing.
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def mock_arq(monkeypatch):
    """Stub out the ARQ task queue."""
    fake_arq = AsyncMock()
    fake_arq.enqueue_job = AsyncMock(return_value=None)

    async def _get_arq_pool():
        return fake_arq

    monkeypatch.setattr("app.core.arq.get_arq_pool", _get_arq_pool)
    # Also patch the reference imported at module level in the swipes endpoint
    try:
        import app.api.v1.swipes.endpoints as swipe_ep
        monkeypatch.setattr(swipe_ep, "get_arq_pool", _get_arq_pool)
    except (ImportError, AttributeError):
        pass


# ---------------------------------------------------------------------------
# WebSocket pub/sub mock — avoids Redis pub/sub during lifespan startup.
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def mock_websocket_pubsub(monkeypatch):
    """Mock WebSocket connection manager pub/sub listener."""
    try:
        from app.core import websocket_manager as ws_mod
        monkeypatch.setattr(
            ws_mod.connection_manager, "start_pubsub_listener", AsyncMock()
        )
        monkeypatch.setattr(
            ws_mod.connection_manager, "stop_pubsub_listener", AsyncMock()
        )
        monkeypatch.setattr(
            ws_mod.connection_manager, "get_all_connections", MagicMock(return_value=[])
        )
    except (ImportError, AttributeError):
        pass


# ---------------------------------------------------------------------------
# Override FastAPI database dependency to use the test session.
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture
async def async_client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """
    Provide an httpx AsyncClient backed by the FastAPI app.

    The app's get_db dependency is overridden to yield the test session so all
    requests in a test share the same transactional session and thus see any
    data seeded in that test.
    """
    from app.core.database import get_db
    from app.main import app

    async def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        yield client

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Seeded fixtures
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture
async def test_user(db_session: AsyncSession):
    """Persisted job-seeker user for integration tests."""
    from app.core.security import get_password_hash
    from app.models.user import User, UserRole

    user = User(
        id=uuid.uuid4(),
        email="seeker@example.com",
        password_hash=get_password_hash("Password1"),
        full_name="Job Seeker",
        role=UserRole.JOB_SEEKER,
        skills=["python", "fastapi"],
        seniority="mid",
        preferred_locations=["remote", "san francisco"],
        # Keep profile_embedding as None so the discover endpoint uses the
        # simple recency fallback path (avoids pgvector <=> operator which
        # is not supported by the SQLite test database).
        profile_embedding=None,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def test_company(db_session: AsyncSession):
    """Persisted company for integration tests."""
    from app.models.company import Company

    company = Company(
        id=uuid.uuid4(),
        name="Test Company Inc",
        description="A test company",
        industry="Software",
        size="11-50",
        location="San Francisco",
        is_active=True,
        is_verified=False,
    )
    db_session.add(company)
    await db_session.flush()
    return company


@pytest_asyncio.fixture
async def test_company_admin(db_session: AsyncSession, test_company):
    """Persisted company admin user linked to test_company."""
    from app.core.security import get_password_hash
    from app.models.user import User, UserRole

    user = User(
        id=uuid.uuid4(),
        email="admin@testcompany.com",
        password_hash=get_password_hash("Password1"),
        full_name="Company Admin",
        role=UserRole.COMPANY_ADMIN,
        company_id=test_company.id,
        profile_embedding=ZERO_EMBEDDING,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def test_job(db_session: AsyncSession, test_company):
    """Persisted active job for integration tests."""
    from datetime import datetime, timezone
    from app.models.job import Job

    job = Job(
        id=uuid.uuid4(),
        title="Software Engineer",
        company_id=test_company.id,
        location="San Francisco",
        short_description="A great engineering job",
        description="Full description here",
        tags=["python", "fastapi", "postgresql"],
        seniority="mid",
        salary_min=80000,
        salary_max=120000,
        currency="USD",
        remote=False,
        work_arrangement="Hybrid",
        job_type="Full-time",
        is_active=True,
        job_embedding=ZERO_EMBEDDING,
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(job)
    await db_session.flush()
    return job


@pytest.fixture
def user_token(test_user) -> str:
    """Valid access token for the job-seeker test user."""
    from app.core.security import create_access_token
    return create_access_token(data={"sub": str(test_user.id)})


@pytest.fixture
def company_token(test_company_admin) -> str:
    """Valid access token for the company admin test user."""
    from app.core.security import create_access_token
    return create_access_token(data={"sub": str(test_company_admin.id)})


@pytest.fixture
def auth_headers(user_token: str) -> dict[str, str]:
    """Authorization headers for the job-seeker test user."""
    return {"Authorization": f"Bearer {user_token}"}


@pytest.fixture
def company_auth_headers(company_token: str) -> dict[str, str]:
    """Authorization headers for the company admin test user."""
    return {"Authorization": f"Bearer {company_token}"}
