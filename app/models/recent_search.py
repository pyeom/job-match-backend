from sqlalchemy import Column, String, DateTime, JSON, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import uuid
from app.core.database import Base


class RecentSearch(Base):
    __tablename__ = "recent_searches"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    query = Column(String(255))  # Keyword search query
    filters_used = Column(JSON)  # Filters applied in the search

    # Timestamps
    searched_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    def __repr__(self):
        return f"<RecentSearch(id={self.id}, query={self.query}, user_id={self.user_id})>"
