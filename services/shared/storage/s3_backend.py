"""AWS S3 implementation of StorageBackend.

Production object storage on AWS. Unlike the MinIO backend this does NOT take
static access/secret keys or create buckets — it relies on the standard AWS
credential chain (ECS task role / instance profile / env) and assumes the bucket
already exists (Terraform owns it). Set ``S3_ENDPOINT_URL`` to point at a local
S3-compatible server (MinIO, moto) for development or tests.
"""

import io
import logging
import os

from . import StorageBackend

logger = logging.getLogger(__name__)


class S3Backend(StorageBackend):
    """Object storage backed by Amazon S3 via boto3.

    Credentials come from the default AWS credential chain (IAM task role on
    ECS/Fargate, instance profile on EC2, or ``AWS_*`` env vars locally) — no
    static keys are accepted here on purpose. MinIO-specific kwargs
    (``endpoint``, ``access_key``, ``secret_key``, ``secure``) are accepted and
    ignored so the same ``get_storage_backend(...)`` call works for either
    provider.
    """

    def __init__(
        self,
        bucket: str = "documents",
        region: str | None = None,
        endpoint_url: str | None = None,
        **_kwargs,
    ):
        import boto3  # lazy import — only needed when provider="s3"
        from botocore.config import Config

        self.bucket = bucket
        self.region = region or os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION")
        # Optional override for local S3-compatible servers (MinIO/moto).
        self.endpoint_url = endpoint_url or os.getenv("S3_ENDPOINT_URL") or None

        self.client = boto3.client(
            "s3",
            region_name=self.region,
            endpoint_url=self.endpoint_url,
            config=Config(
                signature_version="s3v4",
                retries={"max_attempts": 5, "mode": "standard"},
            ),
        )

    # --- StorageBackend interface ---

    def upload(self, data: bytes, key: str, content_type: str = "application/octet-stream") -> str:
        self.client.upload_fileobj(
            io.BytesIO(data),
            self.bucket,
            key,
            ExtraArgs={"ContentType": content_type},
        )
        return f"{self.bucket}/{key}"

    def download(self, key: str) -> bytes:
        buffer = io.BytesIO()
        self.client.download_fileobj(self.bucket, key, buffer)
        return buffer.getvalue()

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)

    def exists(self, key: str) -> bool:
        from botocore.exceptions import ClientError

        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
                return False
            raise
