from __future__ import annotations

from ranking.core.storage.identity import canonicalize_url, compute_resource_id
from ranking.core.storage.local import LocalStorageProvider
from ranking.core.storage.provider import DownloadedDocument, StorageProvider
from ranking.core.storage.s3 import S3StorageProvider
from ranking.core.storage.s3_aws import AwsS3StorageProvider
from ranking.core.storage.s3_gcs import GcsS3StorageProvider
from ranking.core.storage.tracing import TracingStorageProvider

__all__ = [
    "LocalStorageProvider",
    "S3StorageProvider",
    "AwsS3StorageProvider",
    "GcsS3StorageProvider",
    "TracingStorageProvider",
    "StorageProvider",
    "DownloadedDocument",
    "canonicalize_url",
    "compute_resource_id",
]
