from pydantic import BaseModel
from datetime import datetime
from uuid import UUID


class UploadResponse(BaseModel):
    """Response from POST /upload endpoint"""
    job_id: UUID
    status: str  # pending, processing, completed, failed
    filename: str
    created_at: datetime
    file_size: int

    class Config:
        from_attributes = True  # Enable ORM mode for SQLAlchemy models
