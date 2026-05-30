from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings — loaded from environment variables / .env."""

    # Application
    APP_NAME: str = "Ingest Service"
    DEBUG: bool = False

    # Storage (provider-agnostic)
    STORAGE_PROVIDER: str = "minio"      # "minio" (local) | "s3" (AWS)
    STORAGE_BUCKET: str = "documents"

    # MinIO-specific (ignored when STORAGE_PROVIDER != "minio")
    MINIO_ENDPOINT: str = "minio:9000"
    MINIO_ACCESS_KEY: str = "minioadmin"
    MINIO_SECRET_KEY: str = "minioadmin"
    MINIO_SECURE: bool = False

    # PostgreSQL
    POSTGRES_URL: str = "postgresql://raguser:ragpass@postgres:5432/ragdb"

    # Upload limits — keep in sync with nginx client_max_body_size (120m).
    MAX_FILE_SIZE: int = 120 * 1024 * 1024  # 120 MB

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
