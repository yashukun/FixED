import uuid
from datetime import datetime
from enum import Enum

from sqlalchemy import Column, String, Integer, DateTime, Text, Enum as SQLEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""
    pass


class JobStatus(str, Enum):
    """Job processing status."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class Job(Base):
    """Tracks every uploaded document through the processing pipeline."""
    __tablename__ = "jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    status = Column(SQLEnum(JobStatus), default=JobStatus.PENDING, nullable=False)
    filename = Column(String(255), nullable=False)
    storage_path = Column(String(512), nullable=False)   # provider-agnostic path
    file_size = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow,
                        onupdate=datetime.utcnow, nullable=False)
    error_message = Column(Text, nullable=True)
    result = Column(Text, nullable=True)

    def __repr__(self):
        return f"<Job(id={self.id}, status={self.status}, filename={self.filename})>"
