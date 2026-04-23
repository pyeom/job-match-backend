import logging
import warnings
from typing import List, Optional
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

    # Elasticsearch Configuration
    elasticsearch_url: str = Field(default="http://localhost:9200", env="ELASTICSEARCH_URL")

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

    # Embedding update weights
    # When merging a user's profile embedding with their swipe history the final
    # vector is computed as:
    #   updated = embedding_profile_weight * profile + embedding_history_weight * history_mean
    # Both values must sum to 1.0.  Override via EMBEDDING_PROFILE_WEIGHT /
    # EMBEDDING_HISTORY_WEIGHT environment variables.
    embedding_profile_weight: float = Field(default=0.3, env="EMBEDDING_PROFILE_WEIGHT")
    embedding_history_weight: float = Field(default=0.7, env="EMBEDDING_HISTORY_WEIGHT")

    # S3 / Object Storage Configuration (optional — falls back to local storage)
    s3_endpoint_url: Optional[str] = Field(default=None, env="S3_ENDPOINT_URL")
    s3_access_key_id: Optional[str] = Field(default=None, env="S3_ACCESS_KEY_ID")
    s3_secret_access_key: Optional[str] = Field(default=None, env="S3_SECRET_ACCESS_KEY")
    s3_bucket_name: Optional[str] = Field(default=None, env="S3_BUCKET_NAME")
    s3_region: str = Field(default="us-east-1", env="S3_REGION")

    # CDN base URL — when set, media URLs point here instead of the API
    media_cdn_url: Optional[str] = Field(default=None, env="MEDIA_CDN_URL")

    # DashScope (Qwen) API — optional; if absent, InsightsService falls back to templates
    dashscope_api_key: Optional[str] = Field(default=None, env="DASHSCOPE_API_KEY")
    qwen_model: str = Field(default="qwen-plus", env="QWEN_MODEL")

    workos_api_key: Optional[str] = Field(default=None, env="WORKOS_API_KEY")
    workos_client_id: Optional[str] = Field(default=None, env="WORKOS_CLIENT_ID")

    # Match score weights — must collectively drive the final_score formula.
    # WHY: derived from initial recruiter validation study (Q1 2026).
    # The job-level JobMatchConfig weights override these for individual jobs;
    # these are the system-wide defaults used when no config is present.
    match_score_w_hard: float = Field(default=0.55, env="MATCH_SCORE_W_HARD", description="Hard skills match weight")
    match_score_w_soft: float = Field(default=0.20, env="MATCH_SCORE_W_SOFT", description="Soft/Big Five match weight")
    match_score_w_predictive: float = Field(default=0.10, env="MATCH_SCORE_W_PREDICTIVE", description="Predictive model weight")

    # Rate limits — format: "<max_requests>/<window>" where window is a number of seconds
    # or a human-readable unit (minute, hour).  Values are parsed at call-site via
    # parse_rate_limit() in app/core/config.py.
    # WHY: centralised so ops can tune limits via env vars without a redeploy.
    rate_limit_register: str = Field(default="10/hour", env="RATE_LIMIT_REGISTER")
    rate_limit_login_email: str = Field(default="5/15minute", env="RATE_LIMIT_LOGIN_EMAIL")
    rate_limit_login_ip: str = Field(default="20/15minute", env="RATE_LIMIT_LOGIN_IP")
    rate_limit_swipes: str = Field(default="120/minute", env="RATE_LIMIT_SWIPES")
    rate_limit_discover: str = Field(default="30/minute", env="RATE_LIMIT_DISCOVER")
    rate_limit_global: str = Field(default="300/minute", env="RATE_LIMIT_GLOBAL")

    @property
    def use_s3(self) -> bool:
        return bool(self.s3_bucket_name and self.s3_access_key_id and self.s3_secret_access_key)

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

    # Email / SMTP Configuration
    smtp_host: str = Field(default="", env="SMTP_HOST")
    smtp_port: int = Field(default=587, env="SMTP_PORT")
    smtp_user: str = Field(default="", env="SMTP_USER")
    smtp_password: str = Field(default="", env="SMTP_PASSWORD")
    smtp_from: str = Field(default="noreply@job-match.cl", env="SMTP_FROM")
    smtp_tls: bool = Field(default=True, env="SMTP_TLS")
    # Admin alert email — receives fairness/model alerts; defaults to smtp_from
    admin_alert_email: str = Field(default="", env="ADMIN_ALERT_EMAIL")

    # Public URL used in verification email links
    frontend_url: str = Field(default="http://localhost:8081", env="FRONTEND_URL")

    # CORS - allow frontend origins (filter out None values).
    # Both "localhost" and "127.0.0.1" variants are included because browsers
    # treat them as different origins and may use either depending on how the
    # dev server URL is opened.
    allowed_origins: List[str] = [
        origin for origin in [
            "http://localhost:3000",
            "http://localhost:19006",    # Expo web
            "http://localhost:8081",     # Expo Metro
            "exp://localhost:19000",     # Expo development
            "http://127.0.0.1:3000",
            "http://127.0.0.1:19006",
            "http://127.0.0.1:8081",
            os.getenv("FRONTEND_URL")   # Production frontend (e.g. https://job-match.cl)
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


def parse_rate_limit(value: str) -> tuple[int, int]:
    """Parse a rate limit string into (max_requests, window_seconds).

    Supported formats:
        "10/hour"        -> (10, 3600)
        "5/15minute"     -> (5, 900)
        "120/minute"     -> (120, 60)
        "300/minute"     -> (300, 60)

    Args:
        value: Rate limit string in the form "<count>/<multiplier><unit>".

    Returns:
        Tuple of (max_requests, window_seconds).

    Raises:
        ValueError: If the format is not recognised.
    """
    import re

    match = re.fullmatch(r"(\d+)/(\d*)(\w+)", value.strip())
    if not match:
        raise ValueError(f"Invalid rate limit format: {value!r}")

    count = int(match.group(1))
    multiplier = int(match.group(2)) if match.group(2) else 1
    unit = match.group(3).lower()

    unit_seconds: dict[str, int] = {
        "second": 1,
        "seconds": 1,
        "minute": 60,
        "minutes": 60,
        "hour": 3600,
        "hours": 3600,
    }
    if unit not in unit_seconds:
        raise ValueError(f"Unknown time unit {unit!r} in rate limit {value!r}")

    return count, multiplier * unit_seconds[unit]