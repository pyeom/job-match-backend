from sqlalchemy import Column, Integer, String, DateTime, JSON, Text, Boolean
from sqlalchemy.sql import func
from sqlalchemy.dialects.postgresql import UUID
from pgvector.sqlalchemy import Vector
import uuid
from app.core.database import Base


class Job(Base):
    __tablename__ = "jobs"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    title = Column(String(255), nullable=False, index=True)
    company = Column(String(255), nullable=False, index=True)
    location = Column(String(255))
    description = Column(Text)
    
    # Job metadata
    tags = Column(JSON)  # List of skills/technologies required
    seniority = Column(String(50), index=True)  # Junior, Mid, Senior, Lead, etc.
    salary_min = Column(Integer)
    salary_max = Column(Integer)
    remote = Column(Boolean, default=False)
    
    # ML embedding for job content (384 dimensions for all-MiniLM-L6-v2)  
    job_embedding = Column(Vector(384))
    
    # Status
    is_active = Column(Boolean, default=True, index=True)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    def __repr__(self):
        return f"<Job(id={self.id}, title={self.title}, company={self.company})>"