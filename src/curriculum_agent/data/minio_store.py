from __future__ import annotations

from minio import Minio

from curriculum_agent.config import settings

_client: Minio | None = None

EVIDENCE_BUCKET = "evidence-files"
EXPORT_BUCKET = "exports"


def get_minio() -> Minio:
    global _client
    if _client is None:
        _client = Minio(
            settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key.get_secret_value(),
            secure=False,
        )
    return _client


def ensure_buckets() -> None:
    client = get_minio()
    for bucket in (EVIDENCE_BUCKET, EXPORT_BUCKET):
        if not client.bucket_exists(bucket):
            client.make_bucket(bucket)
