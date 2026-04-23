import uuid
from sqlalchemy import Column, String, ForeignKey, Text, DateTime, Boolean, Integer
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


DEFAULT_PIPELINE_STAGES = [
    {"key": "SUBMITTED",  "order": 1, "label": "Applied",    "description": "",  "color": "#6366f1"},
    {"key": "REVIEW",     "order": 2, "label": "Screening",  "description": "",  "color": "#f59e0b"},
    {"key": "INTERVIEW",  "order": 3, "label": "Interview",  "description": "",  "color": "#3b82f6"},
    {"key": "TECHNICAL",  "order": 4, "label": "Technical",  "description": "",  "color": "#8b5cf6"},
    {"key": "DECISION",   "order": 5, "label": "Offer",      "description": "",  "color": "#10b981"},
]


class PipelineTemplate(Base):
    __tablename__ = "pipeline_templates"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(100), nullable=False)
    stages = Column(JSONB, nullable=False)
    is_default = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class ApplicationStageHistory(Base):
    __tablename__ = "application_stage_history"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    application_id = Column(UUID(as_uuid=True), ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, index=True)
    stage_order = Column(Integer, nullable=False)
    stage_name = Column(String(100), nullable=False)
    entered_at = Column(DateTime(timezone=True), server_default=func.now())
    exited_at = Column(DateTime(timezone=True))
    notes = Column(Text)
    moved_by = Column(UUID(as_uuid=True), ForeignKey("users.id"))

    application = relationship("Application", foreign_keys=[application_id])
    moved_by_user = relationship("User", foreign_keys=[moved_by])
