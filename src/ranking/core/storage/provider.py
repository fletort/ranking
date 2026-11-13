from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import structlog

if TYPE_CHECKING:
    from ranking.core.storage.race_archive import ArchiveArea


@dataclass
class DownloadedDocument:
    url: str
    content: bytes

    original_filename: str | None
    content_type: str | None
    content_length: int

    downloaded_at: datetime


@dataclass
class HealthCheckResult:
    """Result of a health check for a storage provider."""

    success: bool
    backend: str
    details: dict[str, str] = field(default_factory=dict)
    checks: dict[str, bool] = field(default_factory=dict)


class StorageProvider(ABC):
    """Abstract base class for URL-based storage operations.

    All storage areas (HTTP cache, snapshots, redirect pointers, extracted data, documents) are
    addressed by URL. Path/key construction is an internal detail of each provider.
    """

    def __init__(self, plugin_name: str) -> None:
        """Initialize the storage provider scoped to a plugin name."""
        self.plugin_name = plugin_name
        self.log = structlog.get_logger().bind(component="storage")

    @staticmethod
    def compute_resource_id(url: str) -> str:
        """Derive a deterministic SHA-1 resource ID from a canonicalized URL."""
        canonical = StorageProvider._canonicalize_url(url)
        return hashlib.sha1(canonical.encode("utf-8")).hexdigest()  # noqa: S324

    @staticmethod
    def _canonicalize_url(url: str) -> str:
        """Canonicalize URL by sorting query parameters to stabilize resource IDs."""
        parsed = urlparse(url)
        sorted_query = sorted(parse_qsl(parsed.query, keep_blank_values=True))
        canonical_query = urlencode(sorted_query, doseq=True)
        return urlunparse(
            (
                parsed.scheme,
                parsed.netloc,
                parsed.path,
                parsed.params,
                canonical_query,
                parsed.fragment,
            )
        )

    @abstractmethod
    def save_http_cache(self, url: str, content: str) -> None:
        """Persist the HTTP response for a URL as the current cached version."""

    @abstractmethod
    def get_http_cache(self, url: str) -> str | None:
        """Return the current cached HTTP response for a URL, or None if absent."""

    @abstractmethod
    def exists_http_cache(self, url: str) -> bool:
        """Return True if a current cached HTTP response exists for the URL."""

    @abstractmethod
    def delete_http_cache(self, url: str) -> None:
        """Delete the current cached HTTP response for a URL.

        Deleting an absent cache entry is a no-op.
        """

    @abstractmethod
    def save_http_snapshot(self, url: str, content: str, timestamp: str) -> None:
        """Persist a timestamped snapshot of an HTTP response for a URL."""

    @abstractmethod
    def list_http_snapshots(self, url: str) -> list[tuple[str, str]]:
        """Return all snapshots for a URL as a list of (timestamp, content) tuples.

        The list is sorted by timestamp in ascending order.
        """

    @abstractmethod
    def save_redirect(self, url: str, target_url: str) -> None:
        """Persist a redirect pointer mapping an initial URL to its final (canonical) URL."""

    @abstractmethod
    def get_redirect(self, url: str) -> str | None:
        """Return the redirect target URL for a URL, or None if no pointer exists."""

    @abstractmethod
    def exists_redirect(self, url: str) -> bool:
        """Return True if a redirect pointer exists for the URL."""

    @abstractmethod
    def delete_redirect(self, url: str) -> None:
        """Delete the redirect pointer for a URL.

        Deleting an absent pointer is a no-op.
        """

    @abstractmethod
    def save_extracted(self, url: str, data: Any) -> None:
        """Persist extracted JSON data for a URL."""

    @abstractmethod
    def get_extracted(self, url: str) -> Any:
        """Return the extracted JSON data for a URL, or None if absent."""

    @abstractmethod
    def save_document(self, document: DownloadedDocument) -> None:
        """Persist a downloaded document and its metadata for a URL."""

    @abstractmethod
    def get_document(self, url: str) -> DownloadedDocument | None:
        """Return the downloaded document for a URL, or None if absent."""

    @abstractmethod
    def document_exists(self, url: str) -> bool:
        """Return True if a downloaded document exists for the URL."""

    @abstractmethod
    def healthcheck(self) -> HealthCheckResult:
        """Perform a health check on the storage provider.

        Returns:
            HealthCheckResult: The result of the health check.
        """

    def download_area_archive(self, race_url: str, area: ArchiveArea, target: Path) -> bool:
        """Download the per-race layer archive into ``target``.

        Returns ``True`` when an archive existed and was written to ``target``. The default
        implementation reports that the backend does not support race archives.
        """
        return False

    def upload_area_archive(self, race_url: str, area: ArchiveArea, source: Path) -> None:
        """Upload the per-race layer archive located at ``source``.

        The default implementation is a no-op for backends without race archive support.
        """
        return None

    def race_session(self, race_url: str) -> AbstractContextManager[StorageProvider]:
        """Return a context manager scoping the crawl of a single race.

        The default implementation is a no-op that yields this provider unchanged, so backends
        without archive support (e.g. the local filesystem) keep their flat layout.
        """
        return nullcontext(self)


__all__ = ["StorageProvider"]


def __getattr__(name: str) -> Any:
    """Lazily expose provider implementations for backward-compatible imports."""
    if name == "LocalStorageProvider":
        from ranking.core.storage import LocalStorageProvider

        return LocalStorageProvider
    if name == "S3StorageProvider":
        from ranking.core.storage import S3StorageProvider

        return S3StorageProvider
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
