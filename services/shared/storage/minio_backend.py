"""MinIO implementation of StorageBackend."""

import io
import logging
import os

from minio import Minio
from minio.error import S3Error

from . import StorageBackend

logger = logging.getLogger(__name__)


class MinIOBackend(StorageBackend):
    """S3-compatible storage via MinIO."""

    def __init__(
        self,
        endpoint: str | None = None,
        access_key: str | None = None,
        secret_key: str | None = None,
        bucket: str = "documents",
        secure: bool = False,
        **_kwargs,
    ):
        self.endpoint = endpoint or os.getenv("MINIO_ENDPOINT", "minio:9000")
        self.access_key = access_key or os.getenv("MINIO_ACCESS_KEY", "minioadmin")
        self.secret_key = secret_key or os.getenv("MINIO_SECRET_KEY", "minioadmin")
        self.bucket = bucket

        self.client = Minio(
            self.endpoint,
            access_key=self.access_key,
            secret_key=self.secret_key,
            secure=secure,
        )
        self._ensure_bucket()

    def _ensure_bucket(self):
        """Create bucket if it doesn't exist."""
        try:
            if not self.client.bucket_exists(self.bucket):
                self.client.make_bucket(self.bucket)
                logger.info("Created bucket: %s", self.bucket)
        except S3Error as e:
            logger.warning("Bucket check failed: %s", e)

    # --- StorageBackend interface ---

    def upload(self, data: bytes, key: str, content_type: str = "application/octet-stream") -> str:
        stream = io.BytesIO(data)
        self.client.put_object(
            self.bucket, key, stream,
            length=len(data),
            content_type=content_type,
        )
        return f"{self.bucket}/{key}"

    def download(self, key: str) -> bytes:
        response = self.client.get_object(self.bucket, key)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()

    def delete(self, key: str) -> None:
        self.client.remove_object(self.bucket, key)

    def exists(self, key: str) -> bool:
        try:
            self.client.stat_object(self.bucket, key)
            return True
        except S3Error:
            return False
