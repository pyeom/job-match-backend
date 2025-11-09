"""
Push token model for storing device push notification tokens.
"""

from sqlalchemy import Column, String, DateTime, ForeignKey, Boolean, CheckConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid
import enum

from app.core.database import Base


class PushTokenPlatform(str, enum.Enum):
    """Platform types for push tokens."""
    IOS = "ios"
    ANDROID = "android"
    WEB = "web"


class PushToken(Base):
    """
    Push notification token model.

    Stores device tokens for Expo Push Notifications.
    Each device can have one active token at a time.
    Either user_id or company_id must be set, but not both.
    """
    __tablename__ = "push_tokens"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
        index=True
    )
    company_id = Column(
        UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=True,
        index=True
    )

    token = Column(String(255), nullable=False, unique=True, index=True)
    platform = Column(String(20), nullable=False)
    device_name = Column(String(255), nullable=True)

    is_active = Column(Boolean, nullable=False, default=True, index=True)
    last_used_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    user = relationship("User", foreign_keys=[user_id])
    company = relationship("Company", foreign_keys=[company_id])

    # Constraint: either user_id or company_id must be set, but not both
    __table_args__ = (
        CheckConstraint(
            '(user_id IS NOT NULL AND company_id IS NULL) OR (user_id IS NULL AND company_id IS NOT NULL)',
            name='check_recipient'
        ),
    )

    def __repr__(self):
        owner = f"user={self.user_id}" if self.user_id else f"company={self.company_id}"
        return f"<PushToken(id={self.id}, {owner}, platform={self.platform}, active={self.is_active})>"
