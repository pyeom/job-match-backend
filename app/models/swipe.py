from sqlalchemy import Column, DateTime, ForeignKey, Index, String, UniqueConstraint, Boolean, text
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

    # Undo tracking
    is_undone = Column(Boolean, default=False, nullable=False, index=True)
    undone_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    user = relationship("User")
    job = relationship("Job")

    # Ensure one swipe per user-job pair
    __table_args__ = (
        UniqueConstraint('user_id', 'job_id', name='unique_user_job_swipe'),
        # Discover endpoint: exclude already-swiped jobs (from migration n0o1p2q3r4s5)
        Index('ix_swipes_user_is_undone', 'user_id', 'is_undone'),
        # Undo window: find recent swipes within the 2-minute session window (from migration q3r4s5t6u7v8)
        Index('ix_swipes_user_created_at', 'user_id', text('created_at DESC')),
    )

    def __repr__(self):
        return f"<Swipe(user_id={self.user_id}, job_id={self.job_id}, direction={self.direction}, is_undone={self.is_undone})>"