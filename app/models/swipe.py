from sqlalchemy import Column, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.sql import func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import uuid
from app.core.database import Base


class Swipe(Base):
    __tablename__ = "swipes"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.id"), nullable=False, index=True)
    direction = Column(String(10), nullable=False)  # LEFT or RIGHT
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    
    # Relationships
    user = relationship("User")
    job = relationship("Job")
    
    # Ensure one swipe per user-job pair
    __table_args__ = (UniqueConstraint('user_id', 'job_id', name='unique_user_job_swipe'),)
    
    def __repr__(self):
        return f"<Swipe(user_id={self.user_id}, job_id={self.job_id}, direction={self.direction})>"