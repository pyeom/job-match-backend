from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from .config import settings

# Create async engine with asyncpg
engine = create_async_engine(
    settings.database_url,
    echo=settings.app_env == "dev",
    future=True,
    pool_pre_ping=True,
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