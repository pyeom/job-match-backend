from sqlalchemy import Column, DateTime, ForeignKey, Index, String, Text, Integer, UniqueConstraint
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

    # Document attachments
    resume_id = Column(UUID(as_uuid=True), ForeignKey("documents.id", ondelete="SET NULL"), nullable=True, index=True)
    cover_letter_id = Column(UUID(as_uuid=True), ForeignKey("documents.id", ondelete="SET NULL"), nullable=True, index=True)

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
    score = Column(Integer, nullable=True)  # Match score (0-100) at time of application

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    user = relationship("User")
    job = relationship("Job")
    resume_document = relationship("Document", foreign_keys=[resume_id], back_populates="applications_as_resume")
    cover_letter_document = relationship("Document", foreign_keys=[cover_letter_id], back_populates="applications_as_cover_letter")

    __table_args__ = (
        # User's applications filtered by pipeline stage (Matches tab) (from migration q3r4s5t6u7v8)
        Index('ix_applications_user_stage', 'user_id', 'stage'),
        # Applications per job at a given stage (from migration n0o1p2q3r4s5)
        Index('ix_applications_job_stage', 'job_id', 'stage'),
    )

    def __repr__(self):
        return f"<Application(user_id={self.user_id}, job_id={self.job_id}, stage={self.stage}, status={self.status})>"


class RevealedApplication(Base):
    """Audit record that a company recruiter has revealed a candidate's identity.

    One row per application — the UNIQUE constraint on ``application_id``
    makes this a "reveal once, permanent" record.  There is intentionally no
    soft-delete or undo path; the action is irreversible by design.
    """

    __tablename__ = "revealed_applications"

    id = Column(Integer, primary_key=True, autoincrement=True)
    application_id = Column(
        UUID(as_uuid=True),
        ForeignKey("applications.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    revealed_by_user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
    )
    revealed_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    # Snapshot of the application stage at the moment of reveal — for audit.
    stage_at_reveal = Column(String(25), nullable=False)

    # Relationships
    application = relationship("Application", foreign_keys=[application_id])
    revealed_by = relationship("User", foreign_keys=[revealed_by_user_id])

    __table_args__ = (
        UniqueConstraint("application_id", name="uq_revealed_applications_application_id"),
    )

    def __repr__(self):
        return (
            f"<RevealedApplication(application_id={self.application_id}, "
            f"revealed_by={self.revealed_by_user_id}, at={self.revealed_at})>"
        )