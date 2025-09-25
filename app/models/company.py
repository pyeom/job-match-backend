from sqlalchemy import Column, String, DateTime, Text, Boolean, Integer
from sqlalchemy.sql import func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import uuid
from app.core.database import Base


class Company(Base):
    __tablename__ = "companies"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    name = Column(String(255), unique=True, nullable=False, index=True)
    description = Column(Text)
    website = Column(String(500))
    logo_url = Column(String(500))  # Company logo URL
    industry = Column(String(100))
    size = Column(String(50))  # e.g., "1-10", "11-50", "51-200", "201-1000", "1000+"
    location = Column(String(255))  # Company headquarters
    founded_year = Column(Integer)  # Year company was founded
    
    # Company status
    is_verified = Column(Boolean, default=False, index=True)  # For verified companies
    is_active = Column(Boolean, default=True, index=True)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    users = relationship("User", back_populates="company")
    jobs = relationship("Job", back_populates="company")
    
    def __repr__(self):
        return f"<Company(id={self.id}, name={self.name})>"