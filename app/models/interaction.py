from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.sql import func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import uuid
from app.core.database import Base


class Interaction(Base):
    __tablename__ = "interactions"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.id"), nullable=False, index=True)
    
    # ML scoring data for future model improvements
    score_at_view = Column(Integer)  # Score when job was shown (0-100)
    action = Column(String(10))  # RIGHT, LEFT
    
    # Context data for future personalization
    view_duration_ms = Column(Integer)  # How long user viewed the card
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    
    # Relationships
    user = relationship("User")
    job = relationship("Job")
    
    def __repr__(self):
        return f"<Interaction(user_id={self.user_id}, job_id={self.job_id}, action={self.action})>"