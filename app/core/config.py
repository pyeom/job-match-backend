import logging
import warnings
from typing import List
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings
import os
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

_DEFAULT_JWT_SECRET = "change-me-in-production-use-a-secure-random-string"
_INSECURE_DB_PASSWORDS = {"admin", "password", "postgres", "123456", "secret"}


class Settings(BaseSettings):
    # PostgreSQL Configuration
    postgres_user: str = Field(default="admin", env="POSTGRES_USER")
    postgres_password: str = Field(default="admin", env="POSTGRES_PASSWORD")
    postgres_db: str = Field(default="jobsearch", env="POSTGRES_DB")
    postgres_host: str = Field(default="db", env="POSTGRES_HOST")
    postgres_port: int = Field(default=5432, env="POSTGRES_PORT")

    # Application Configuration
    app_env: str = Field(default="dev", env="APP_ENV")
    api_port: int = Field(default=8000, env="API_PORT")
    jwt_secret: str = Field(
        default=_DEFAULT_JWT_SECRET,
        env="JWT_SECRET"
    )
    access_token_expires: int = Field(default=900, env="ACCESS_TOKEN_EXPIRES")  # 15 minutes
    refresh_token_expires: int = Field(default=604800, env="REFRESH_TOKEN_EXPIRES")  # 7 days
    embedding_model: str = Field(default="all-MiniLM-L6-v2", env="EMBEDDING_MODEL")

    # Redis Configuration
    redis_url: str = Field(default="redis://localhost:6379/0", env="REDIS_URL")
    redis_pool_size: int = Field(default=10, env="REDIS_POOL_SIZE")

    # Database connection pool
    db_pool_size: int = Field(default=10, env="DB_POOL_SIZE")
    db_max_overflow: int = Field(default=20, env="DB_MAX_OVERFLOW")
    db_pool_timeout: int = Field(default=30, env="DB_POOL_TIMEOUT")
    db_pool_recycle: int = Field(default=1800, env="DB_POOL_RECYCLE")  # recycle after 30 min
    db_statement_timeout_ms: int = Field(default=30000, env="DB_STATEMENT_TIMEOUT_MS")  # 30s

    # NLP / Resume parsing
    spacy_model_en: str = Field(default="en_core_web_trf", env="SPACY_MODEL_EN")
    spacy_model_es: str = Field(default="es_core_news_lg", env="SPACY_MODEL_ES")
    esco_skill_similarity_threshold: float = Field(default=0.75, env="ESCO_SKILL_THRESHOLD")
    esco_index_path: str = Field(default="app/data/esco/skills_index.pkl", env="ESCO_INDEX_PATH")

    @model_validator(mode="after")
    def validate_production_requirements(self) -> "Settings":
        is_production = self.app_env == "production"

        # --- JWT secret ---
        if self.jwt_secret == _DEFAULT_JWT_SECRET:
            if is_production:
                raise ValueError(
                    "JWT_SECRET must be set to a secure value in production. "
                    "Generate one with: openssl rand -hex 32"
                )
            warnings.warn(
                "Using default JWT_SECRET — this is NOT safe for production.",
                stacklevel=2,
            )
        elif len(self.jwt_secret) < 32 and is_production:
            raise ValueError(
                "JWT_SECRET must be at least 32 characters in production."
            )

        # --- Database password ---
        if self.postgres_password in _INSECURE_DB_PASSWORDS and is_production:
            raise ValueError(
                f"Insecure database password '{self.postgres_password}' detected in production. "
                "Set POSTGRES_PASSWORD to a strong secret."
            )

        # --- Redis URL ---
        if is_production and ("localhost" in self.redis_url or "127.0.0.1" in self.redis_url):
            raise ValueError(
                "REDIS_URL must point to an external Redis instance in production, "
                "not localhost. Current value: " + self.redis_url
            )

        return self

    @property
    def database_url(self) -> str:
        return f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"

    # CORS - allow frontend origins (filter out None values)
    allowed_origins: List[str] = [
        origin for origin in [
            "http://localhost:3000",
            "http://localhost:19006",  # Expo web
            "http://localhost:8081",   # Expo Metro
            "exp://localhost:19000",   # Expo development
            os.getenv("FRONTEND_URL")
        ] if origin is not None
    ]

    def log_config(self) -> None:
        """Log active configuration at startup with secrets masked."""
        secret_tail = "***" + self.jwt_secret[-4:] if len(self.jwt_secret) >= 4 else "***"
        logger.info("Configuration loaded:")
        logger.info("  app_env=%s", self.app_env)
        logger.info("  jwt_secret=%s", secret_tail)
        logger.info(
            "  database=%s:%s/%s",
            self.postgres_host, self.postgres_port, self.postgres_db,
        )
        logger.info("  redis_url=%s", self.redis_url)
        logger.info("  embedding_model=%s", self.embedding_model)

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()