from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from .config import settings

# Create async engine with asyncpg
engine = create_async_engine(
    settings.database_url,
    echo=settings.app_env == "dev",
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_timeout=settings.db_pool_timeout,
    pool_recycle=settings.db_pool_recycle,
    pool_pre_ping=True,
    connect_args={
        "command_timeout": settings.db_statement_timeout_ms / 1000,
        "server_settings": {
            "statement_timeout": str(settings.db_statement_timeout_ms),
        },
    },
)

# AsyncSessionLocal class for creating async database sessions
AsyncSessionLocal = async_sessionmaker(
    engine, 
    class_=AsyncSession, 
    expire_on_commit=False
)

# Base class for SQLAlchemy models
Base = declarative_base()


# Dependency to get async DB session
async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()