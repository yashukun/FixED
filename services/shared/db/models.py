import uuid
from datetime import datetime
from enum import Enum

from pgvector.sqlalchemy import Vector
from sqlalchemy import Column, String, Integer, DateTime, Text, Enum as SQLEnum, Numeric, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import DeclarativeBase

from embedding import EMBEDDING_DIMENSIONS


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
    
    # Vector size is the single shared constant (default 1536). Every service
    # embeds at this dimensionality; see services/shared/embedding.py.
    embedding = Column(Vector(EMBEDDING_DIMENSIONS))
    
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
    chat_session_id = Column(String(128), nullable=True, index=True)
    query = Column(Text, nullable=False)
    file_id = Column(String(255), nullable=True, index=True)
    scope = Column(String(64), nullable=False, default="factoid")
    task = Column(String(64), nullable=False, default="qa")
    style = Column(String(64), nullable=False, default="default")
    language = Column(String(16), nullable=False, default="en")
    response_kind = Column(String(32), nullable=False, default="answer")
    answer = Column(Text, nullable=False, default="")
    results_json = Column(JSONB, nullable=False, default=list)
    cost_usd = Column(Numeric(16, 8), nullable=False, default=0)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    __table_args__ = (
        Index("ix_search_history_file_created_at", "file_id", "created_at"),
        Index("ix_search_history_session_created_at", "chat_session_id", "created_at"),
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


class VivaSessionStatus(str, Enum):
    """Lifecycle status for a viva session."""

    PENDING = "pending"
    ACTIVE = "active"
    COMPLETED = "completed"
    TERMINATED_PROCTORING = "terminated_proctoring"
    TERMINATED_TIMEOUT = "terminated_timeout"


class VivaSession(Base):
    """Stores one viva session and high-level policy/config state."""

    __tablename__ = "viva_sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    file_id = Column(String(255), nullable=False, index=True)
    topic = Column(Text, nullable=False)
    chapter_number = Column(Integer, nullable=True)
    question_count = Column(Integer, nullable=False, default=5)
    per_question_limit_seconds = Column(Integer, nullable=False, default=60)
    session_limit_seconds = Column(Integer, nullable=False, default=600)
    status = Column(SQLEnum(VivaSessionStatus), nullable=False, default=VivaSessionStatus.PENDING)
    warning_count = Column(Integer, nullable=False, default=0)
    current_question_index = Column(Integer, nullable=False, default=0)
    reference_photo_b64 = Column(Text, nullable=True)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    termination_reason = Column(String(128), nullable=True)
    # Pause/resume support: when a candidate navigates away mid-viva the session
    # is paused so the wall-clock `session_limit_seconds` does not run against
    # them while gone. `paused_at` is set while currently paused; on resume the
    # paused span is banked into `total_paused_seconds` and excluded from the
    # elapsed-time computation (see _active_elapsed_seconds in viva/main.py).
    paused_at = Column(DateTime, nullable=True)
    total_paused_seconds = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ix_viva_sessions_file_created_at", "file_id", "created_at"),
    )


class VivaQuestion(Base):
    """Generated viva questions tied to a session."""

    __tablename__ = "viva_questions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    question_order = Column(Integer, nullable=False)
    question_text = Column(Text, nullable=False)
    expected_points_json = Column(JSONB, nullable=False, default=list)
    asked_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    __table_args__ = (
        Index("ix_viva_questions_session_order", "session_id", "question_order"),
    )


class VivaTurn(Base):
    """Stores each student answer turn and evaluator output."""

    __tablename__ = "viva_turns"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    question_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    answer_transcript = Column(Text, nullable=False, default="")
    answer_audio_b64 = Column(Text, nullable=True)
    score = Column(Numeric(6, 2), nullable=False, default=0)
    max_score = Column(Numeric(6, 2), nullable=False, default=10)
    strengths_json = Column(JSONB, nullable=False, default=list)
    weaknesses_json = Column(JSONB, nullable=False, default=list)
    feedback = Column(Text, nullable=False, default="")
    latency_ms = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    __table_args__ = (
        Index("ix_viva_turns_session_created_at", "session_id", "created_at"),
    )


class VivaProctorEvent(Base):
    """Stores frame-level proctoring checks and warning escalations."""

    __tablename__ = "viva_proctor_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    event_type = Column(String(64), nullable=False, default="frame_check")
    is_present = Column(Integer, nullable=False, default=1)
    is_match = Column(Integer, nullable=False, default=1)
    confidence = Column(Numeric(5, 4), nullable=False, default=1)
    warning_count = Column(Integer, nullable=False, default=0)
    action = Column(String(64), nullable=False, default="ok")
    details_json = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    __table_args__ = (
        Index("ix_viva_proctor_session_created_at", "session_id", "created_at"),
    )


class VivaResult(Base):
    """Final evaluated result snapshot for a viva session."""

    __tablename__ = "viva_results"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID(as_uuid=True), nullable=False, unique=True, index=True)
    overall_score = Column(Numeric(6, 2), nullable=False, default=0)
    max_score = Column(Numeric(6, 2), nullable=False, default=0)
    strengths_json = Column(JSONB, nullable=False, default=list)
    weak_areas_json = Column(JSONB, nullable=False, default=list)
    recommendations_json = Column(JSONB, nullable=False, default=list)
    question_breakdown_json = Column(JSONB, nullable=False, default=list)
    summary = Column(Text, nullable=False, default="")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
