from sqlalchemy import Column, String, DateTime, ForeignKey, Boolean, Text, Enum
from sqlalchemy.sql import func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import uuid
import enum
from app.core.database import Base


class NotificationType(str, enum.Enum):
    APPLICATION_UPDATE = "APPLICATION_UPDATE"
    NEW_APPLICATION = "NEW_APPLICATION"
    JOB_MATCH = "JOB_MATCH"
    MESSAGE = "MESSAGE"
    SYSTEM = "SYSTEM"
    PROMOTION = "PROMOTION"


class DeliveryStatus(str, enum.Enum):
    pending = "pending"
    delivered = "delivered"
    failed = "failed"


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=True, index=True)

    title = Column(String(255), nullable=False)
    message = Column(Text, nullable=False)
    type = Column(Enum(NotificationType), nullable=False, index=True)

    is_read = Column(Boolean, nullable=False, default=False, index=True)
    read_at = Column(DateTime(timezone=True), nullable=True)

    # Related entities
    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.id"), nullable=True, index=True)
    application_id = Column(UUID(as_uuid=True), ForeignKey("applications.id"), nullable=True, index=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    # Push delivery tracking
    delivery_status = Column(
        Enum(DeliveryStatus, name="deliverystatus"),
        nullable=False,
        default=DeliveryStatus.pending,
        server_default="pending",
    )

    # Relationships
    user = relationship("User", foreign_keys=[user_id])
    company = relationship("Company", foreign_keys=[company_id])
    job = relationship("Job", foreign_keys=[job_id])
    application = relationship("Application", foreign_keys=[application_id])

    def __repr__(self):
        recipient = f"user={self.user_id}" if self.user_id else f"company={self.company_id}"
        return f"<Notification(id={self.id}, {recipient}, type={self.type}, is_read={self.is_read})>"
