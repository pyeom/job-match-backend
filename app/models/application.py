from sqlalchemy import Column, DateTime, ForeignKey, String, Text
from sqlalchemy.sql import func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import uuid
from app.core.database import Base


class Application(Base):
    __tablename__ = "applications"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.id"), nullable=False, index=True)
    
    # Application status
    status = Column(String(20), nullable=False, default="SUBMITTED", index=True)  # SUBMITTED, REJECTED, ACCEPTED
    
    # Optional fields
    cover_letter = Column(Text)
    notes = Column(Text)  # Internal notes for tracking
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    user = relationship("User")
    job = relationship("Job")
    
    def __repr__(self):
        return f"<Application(user_id={self.user_id}, job_id={self.job_id}, status={self.status})>"