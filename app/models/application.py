from sqlalchemy import Column, DateTime, ForeignKey, String, Text
from sqlalchemy.sql import func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
import uuid
from app.core.database import Base


class Application(Base):
    __tablename__ = "applications"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.id"), nullable=False, index=True)

    # New 5-stage pipeline fields
    stage = Column(String(25), nullable=False, default="SUBMITTED", index=True)
    # Values: SUBMITTED, REVIEW, INTERVIEW, TECHNICAL, DECISION

    status = Column(String(25), nullable=False, default="ACTIVE", index=True)
    # Values: ACTIVE, HIRED, REJECTED (replaces old status field)

    stage_updated_at = Column(DateTime(timezone=True), server_default=func.now())
    # Tracks when stage last changed

    rejection_reason = Column(Text, nullable=True)
    # Required when status=REJECTED

    stage_history = Column(JSONB, nullable=True, default=list)
    # JSON array tracking stage transitions: [{"from_stage": "...", "to_stage": "...", "timestamp": "...", "changed_by": "user_id"}]

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
        return f"<Application(user_id={self.user_id}, job_id={self.job_id}, stage={self.stage}, status={self.status})>"