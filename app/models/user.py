from sqlalchemy import Column, Integer, String, DateTime, JSON, Text
from sqlalchemy.sql import func
from sqlalchemy.dialects.postgresql import UUID
from pgvector.sqlalchemy import Vector
import uuid
from app.core.database import Base


class User(Base):
    __tablename__ = "users"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    
    # Profile information
    full_name = Column(String(255))
    headline = Column(Text)
    skills = Column(JSON)  # List of skills
    preferred_locations = Column(JSON)  # List of preferred locations
    seniority = Column(String(50))  # Junior, Mid, Senior, Lead, etc.
    
    # ML embedding for user profile (384 dimensions for all-MiniLM-L6-v2)
    profile_embedding = Column(Vector(384))
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    def __repr__(self):
        return f"<User(id={self.id}, email={self.email})>"