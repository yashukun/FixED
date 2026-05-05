import uuid
from datetime import datetime
from enum import Enum

from pgvector.sqlalchemy import Vector
from sqlalchemy import Column, String, Integer, DateTime, Text, Enum as SQLEnum
from sqlalchemy.dialects.postgresql import UUID, JSONB
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


class DocumentChunk(Base):
    """
    Stores document chunks and their vector embeddings using pgvector.
    
    NOTE: We are using pgvector locally for development to avoid cloud dependencies.
    In the future, we will transition to Pinecone for production use.
    This table stores the same data that would be sent to Pinecone.
    """
    __tablename__ = "document_chunks"

    id = Column(String(255), primary_key=True) # E.g., "{file_id}_{chunk_index}"
    file_id = Column(String(255), nullable=False, index=True)
    chunk_index = Column(Integer, nullable=False)
    text_content = Column(Text, nullable=False)
    filename = Column(String(255), nullable=False)
    
    # We use 1536 as the dimension for OpenAI's text-embedding-3-small
    embedding = Column(Vector(1536))
    
    # Store any extra metadata (like Pinecone does)
    metadata_ = Column("metadata", JSONB, nullable=True)

    def __repr__(self):
        return f"<DocumentChunk(id={self.id}, file_id={self.file_id}, index={self.chunk_index})>"
