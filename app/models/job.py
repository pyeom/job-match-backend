from sqlalchemy import Column, Integer, String, DateTime, JSON, Text, Boolean, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from pgvector.sqlalchemy import Vector
import uuid
from app.core.database import Base


class Job(Base):
    __tablename__ = "jobs"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    title = Column(String(255), nullable=False, index=True)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False, index=True)
    location = Column(String(255))
    short_description = Column(String(500))  # Short description for job cards
    description = Column(Text)  # Full description for detailed job views
    
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
    
    # Relationships
    company = relationship("Company", back_populates="jobs")
    
    def __repr__(self):
        return f"<Job(id={self.id}, title={self.title}, company_id={self.company_id})>"