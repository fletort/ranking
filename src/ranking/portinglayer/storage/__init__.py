from __future__ import annotations

from ranking.portinglayer.storage.local import LocalStorageProvider
from ranking.portinglayer.storage.s3 import S3StorageProvider

__all__ = ["LocalStorageProvider", "S3StorageProvider"]
