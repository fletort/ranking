from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse


class StorageProvider(ABC):
    """Abstract base class for URL-based storage operations.

    All storage areas (HTTP cache, snapshots, extracted data, documents) are
    addressed by URL. Path/key construction is an internal detail of each provider.
    """

    def __init__(self, plugin_name: str) -> None:
        """Initialize the storage provider scoped to a plugin name."""
        self.plugin_name = plugin_name

    def _compute_resource_id(self, url: str) -> str:
        """Derive a deterministic SHA-1 resource ID from a canonicalized URL."""
        canonical = self._canonicalize_url(url)
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
    def save_http_snapshot(self, url: str, content: str, timestamp: str) -> None:
        """Persist a timestamped snapshot of an HTTP response for a URL."""

    @abstractmethod
    def list_http_snapshots(self, url: str) -> list[tuple[str, str]]:
        """Return all snapshots for a URL as a list of (timestamp, content) tuples.

        The list is sorted by timestamp in ascending order.
        """

    @abstractmethod
    def save_extracted(self, url: str, data: Any) -> None:
        """Persist extracted JSON data for a URL."""

    @abstractmethod
    def get_extracted(self, url: str) -> Any:
        """Return the extracted JSON data for a URL, or None if absent."""

    @abstractmethod
    def save_document(self, url: str, content: bytes, metadata: dict[str, Any]) -> None:
        """Persist a downloaded document and its metadata for a URL."""

    @abstractmethod
    def get_document(self, url: str) -> tuple[bytes, dict[str, Any]] | None:
        """Return the (content, metadata) for a downloaded document, or None if absent."""

    @abstractmethod
    def document_exists(self, url: str) -> bool:
        """Return True if a downloaded document exists for the URL."""


__all__ = ["StorageProvider", "LocalStorageProvider", "S3StorageProvider"]

if TYPE_CHECKING:
    from ranking.portinglayer.storage.local import LocalStorageProvider
    from ranking.portinglayer.storage.s3 import S3StorageProvider


def __getattr__(name: str) -> type[LocalStorageProvider] | type[S3StorageProvider]:
    if name == "LocalStorageProvider":
        from ranking.portinglayer.storage import LocalStorageProvider

        return LocalStorageProvider
    if name == "S3StorageProvider":
        from ranking.portinglayer.storage import S3StorageProvider

        return S3StorageProvider
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
