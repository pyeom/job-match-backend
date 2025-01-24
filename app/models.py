from sqlalchemy import Column, Integer, String, Float
from .database import Base

class Job(Base):
    __tablename__ = "jobs"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, index=True)
    description = Column(String)
    embedding = Column(String)  # Store as JSON or serialized array

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    preferences = Column(String)  # Store JSON preferences
