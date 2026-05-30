"""
Abstract storage backend.

To swap providers (MinIO → S3 → GCS), implement StorageBackend
and register in get_storage_backend().
"""

from abc import ABC, abstractmethod


class StorageBackend(ABC):
    """Interface every storage provider must implement."""

    @abstractmethod
    def upload(self, data: bytes, key: str, content_type: str = "application/octet-stream") -> str:
        """Upload bytes and return the full storage path."""
        ...

    @abstractmethod
    def download(self, key: str) -> bytes:
        """Download and return file content as bytes."""
        ...

    @abstractmethod
    def delete(self, key: str) -> None:
        """Delete an object by key."""
        ...

    @abstractmethod
    def exists(self, key: str) -> bool:
        """Check if an object exists."""
        ...


def get_storage_backend(provider: str = "minio", **kwargs) -> StorageBackend:
    """
    Factory — returns the correct backend based on provider name.

    Args:
        provider: "minio" or "s3" (add more as needed)
        **kwargs: passed directly to the backend constructor;
                  if omitted the backend reads from env vars.
    """
    if provider == "minio":
        from .minio_backend import MinIOBackend
        return MinIOBackend(**kwargs)
    if provider == "s3":
        from .s3_backend import S3Backend
        return S3Backend(**kwargs)
    raise ValueError(f"Unknown storage provider: {provider}")
