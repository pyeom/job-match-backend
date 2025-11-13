from typing import List
from pydantic import Field
from pydantic_settings import BaseSettings
import os
from dotenv import load_dotenv

load_dotenv()


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
        default="change-me-in-production-use-a-secure-random-string", 
        env="JWT_SECRET"
    )
    access_token_expires: int = Field(default=900, env="ACCESS_TOKEN_EXPIRES")  # 15 minutes
    refresh_token_expires: int = Field(default=604800, env="REFRESH_TOKEN_EXPIRES")  # 7 days
    embedding_model: str = Field(default="all-MiniLM-L6-v2", env="EMBEDDING_MODEL")
    
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
    
    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()