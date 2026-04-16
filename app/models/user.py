from sqlalchemy import Column, String, DateTime, JSON, Text, ForeignKey, Enum, Boolean
from sqlalchemy.sql import func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from pgvector.sqlalchemy import Vector
import uuid
import enum
from app.core.database import Base


class UserRole(str, enum.Enum):
    JOB_SEEKER = "job_seeker"
    COMPANY_RECRUITER = "company_recruiter"
    COMPANY_ADMIN = "company_admin"
    PLATFORM_ADMIN = "platform_admin"


class CompanyRole(str, enum.Enum):
    ADMIN = "admin"
    RECRUITER = "recruiter"
    HIRING_MANAGER = "hiring_manager"
    VIEWER = "viewer"


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=True)
    auth_provider = Column(String(50), nullable=False, server_default="local", index=True)
    external_id = Column(String(255), nullable=True, index=True)

    # User role and company relationship
    role = Column(Enum(UserRole), nullable=False, default=UserRole.JOB_SEEKER, index=True)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=True, index=True)
    company_role = Column(Enum(CompanyRole, values_callable=lambda x: [e.value for e in x]), nullable=True, index=True)

    # Profile information
    full_name = Column(String(255))
    headline = Column(Text)
    bio = Column(Text)  # User biography/summary
    skills = Column(JSON)  # List of skills
    preferred_locations = Column(JSON)  # List of preferred locations
    work_arrangement = Column(JSON)  # List of preferred work arrangements (Remote, Hybrid, On-site)
    seniority = Column(String(50))  # Junior, Mid, Senior, Lead, etc.
    phone = Column(String(20))  # Phone number
    experience = Column(JSON)  # List of work experience objects
    education = Column(JSON)  # List of education objects
    avatar_url = Column(String(500))  # URL to standard avatar (512x512)
    avatar_thumbnail_url = Column(String(500))  # URL to thumbnail avatar (256x256)

    # ML embedding for user profile (384 dimensions for all-MiniLM-L6-v2)
    profile_embedding = Column(Vector(384))

    # Email verification
    email_verified = Column(Boolean, nullable=False, default=False)

    # Demographic (optional, self-reported — used only for fairness auditing)
    gender_identity = Column(String(50), nullable=True)

    # Localization
    timezone = Column(String(64), nullable=True, default="UTC")

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    company = relationship("Company", back_populates="users")
    documents = relationship("Document", back_populates="user", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<User(id={self.id}, email={self.email}, role={self.role})>"