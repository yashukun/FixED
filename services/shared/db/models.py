import uuid
from datetime import datetime
from enum import Enum

from pgvector.sqlalchemy import Vector
from sqlalchemy import Column, String, Integer, DateTime, Text, Enum as SQLEnum, Numeric, Index
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


class BookChapter(Base):
    """Stores chapter boundaries detected for each uploaded book."""
    __tablename__ = "book_chapters"

    id = Column(String(255), primary_key=True)  # E.g., "{file_id}_{chapter_number}"
    file_id = Column(String(255), nullable=False, index=True)
    number = Column(Integer, nullable=False)
    title = Column(String(512), nullable=False)
    start_page = Column(Integer, nullable=False)
    end_page = Column(Integer, nullable=False)

    def __repr__(self):
        return (
            f"<BookChapter(file_id={self.file_id}, number={self.number}, "
            f"range={self.start_page}-{self.end_page})>"
        )


class ApiCostEvent(Base):
    """Stores model-usage and estimated cost details per API request segment."""

    __tablename__ = "api_cost_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    service = Column(String(64), nullable=False, index=True)
    kind = Column(String(64), nullable=False)
    model = Column(String(128), nullable=False)
    prompt_tokens = Column(Integer, nullable=False, default=0)
    completion_tokens = Column(Integer, nullable=False, default=0)
    total_tokens = Column(Integer, nullable=False, default=0)
    cost_usd = Column(Numeric(16, 8), nullable=False, default=0)
    file_id = Column(String(255), nullable=True, index=True)
    meta = Column(JSONB, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    __table_args__ = (
        Index("ix_api_cost_events_service_created_at", "service", "created_at"),
    )

    def __repr__(self):
        return (
            f"<ApiCostEvent(service={self.service}, kind={self.kind}, model={self.model}, "
            f"tokens={self.total_tokens}, cost_usd={self.cost_usd})>"
        )


class SearchHistory(Base):
    """Stores persisted search requests and generated responses."""

    __tablename__ = "search_history"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    query = Column(Text, nullable=False)
    file_id = Column(String(255), nullable=True, index=True)
    scope = Column(String(64), nullable=False, default="factoid")
    task = Column(String(64), nullable=False, default="qa")
    style = Column(String(64), nullable=False, default="default")
    language = Column(String(16), nullable=False, default="en")
    answer = Column(Text, nullable=False, default="")
    results_json = Column(JSONB, nullable=False, default=list)
    cost_usd = Column(Numeric(16, 8), nullable=False, default=0)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    __table_args__ = (
        Index("ix_search_history_file_created_at", "file_id", "created_at"),
    )

    def __repr__(self):
        return (
            f"<SearchHistory(id={self.id}, file_id={self.file_id}, "
            f"query={self.query[:40]!r})>"
        )


class GeneratedPaper(Base):
    """Stores generated question papers and metadata for retrieval."""

    __tablename__ = "generated_papers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    file_id = Column(String(255), nullable=False, index=True)
    topic = Column(Text, nullable=False)
    mode = Column(String(32), nullable=False, default="official")
    total_marks = Column(Integer, nullable=False)
    distribution_json = Column(JSONB, nullable=False, default=dict)
    paper_json = Column(JSONB, nullable=False, default=dict)
    retrieval_json = Column(JSONB, nullable=False, default=list)
    cost_usd = Column(Numeric(16, 8), nullable=False, default=0)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    __table_args__ = (
        Index("ix_generated_papers_file_created_at", "file_id", "created_at"),
    )

    def __repr__(self):
        return (
            f"<GeneratedPaper(id={self.id}, file_id={self.file_id}, mode={self.mode}, "
            f"topic={self.topic[:40]!r})>"
        )
