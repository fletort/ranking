from __future__ import annotations

from ranking.core.storage.local import LocalStorageProvider
from ranking.core.storage.provider import DownloadedDocument, StorageProvider
from ranking.core.storage.s3 import S3StorageProvider

__all__ = ["LocalStorageProvider", "S3StorageProvider", "StorageProvider", "DownloadedDocument"]
