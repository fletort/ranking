from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable

import structlog

from ranking.core.storage import DownloadedDocument, StorageProvider
from ranking.portinglayer.storage import LocalStorageProvider


class CachePolicy(Enum):
    """Defines v1 cache behavior for each fetch call."""

    NO_CACHE = "NO_CACHE"
    CACHE_IF_PRESENT = "CACHE_IF_PRESENT"
    REFRESH_AND_CACHE = "REFRESH_AND_CACHE"


class CrawlerRuntime(ABC):
    """Orchestrates resource retrieval, cache policies, and artifact persistence.

    Network access is implemented by subclasses.
    Storage is delegated to a StorageProvider.
    """

    def __init__(
        self,
        plugin_name: str,
        cache_root: Path | str = ".cache",
        document_root: Path | str = ".document",
        normalize_for_comparison: Callable[[str, str], str] | None = None,
        save_extracted: bool = False,
        logger: Any = structlog.get_logger(),
        storage: StorageProvider | None = None,
    ) -> None:
        """Initialize a crawler instance scoped to a plugin name.

        Args:
            plugin_name: Logical name of the plugin owning this crawler instance.
            cache_root: Root directory for the local cache (used when *storage* is not provided).
            document_root: Root directory for downloaded documents (used when *storage* is not provided).
            normalize_for_comparison: Optional hook to normalize content before change detection.
            save_extracted: If True, extracted JSON data is persisted via the storage provider.
            logger: Structured logger instance.
            storage: Storage provider to use. Defaults to
                :class:`~ranking.portinglayer.storage.LocalStorageProvider`.
        """
        self.plugin_name = plugin_name
        self.logger = logger
        self.save_extracted = save_extracted

        # Optional normalization hook (plugin-controlled)
        self.normalize_for_comparison = normalize_for_comparison
        self.cache_hits = 0
        self.cache_misses = 0

        if storage is None:
            storage = LocalStorageProvider(
                plugin_name, cache_root=cache_root, document_root=document_root
            )
        self.storage = storage

    @abstractmethod
    def fetcher(self, url: str) -> str:
        """Fetch a resource, without using the cache. This is the network-level fetcher."""
        pass

    def downloader(self, url: str) -> DownloadedDocument:
        """Download a document, without using the document cache."""
        raise NotImplementedError

    def _has_changed(self, url: str, old: str, new: str) -> bool:
        """Determine if content has changed, optionally using a normalization hook."""
        if self.normalize_for_comparison:
            return self.normalize_for_comparison(url, old) != self.normalize_for_comparison(
                url, new
            )
        return old != new

    def fetch(self, url: str, cache_policy: CachePolicy) -> str:
        """Fetch content according to policy and update storage when needed."""
        if cache_policy is CachePolicy.NO_CACHE:
            self.logger.info("No cache policy, fetching directly", url=url)
            return self.fetcher(url)

        existing_content = self.storage.get_http_cache(url)

        if cache_policy is CachePolicy.CACHE_IF_PRESENT:
            if existing_content is not None:
                self.cache_hits += 1
                self.logger.info("Cache hit", url=url)
                return existing_content

            self.cache_misses += 1
            self.logger.info("Cache miss, fetching", url=url)
            content = self.fetcher(url)
            self.storage.save_http_cache(url, content)
            return content

        if cache_policy is CachePolicy.REFRESH_AND_CACHE:
            self.logger.info("Cache refresh", url=url)
            fetched_content = self.fetcher(url)

            if existing_content is None:
                self.logger.info("No existing content, writing current cache", url=url)
                self.storage.save_http_cache(url, fetched_content)

            if existing_content is not None and self._has_changed(
                url, existing_content, fetched_content
            ):
                self.logger.info("Content changed, updating cache", url=url)
                self.storage.save_http_snapshot(url, existing_content, self._snapshot_timestamp())
                self.storage.save_http_cache(url, fetched_content)

            return fetched_content

        return None

    def save_extracted_json(self, url: str, data: Any) -> None:
        """Persist extracted JSON data via the storage provider if save_extracted is enabled."""
        if not self.save_extracted:
            return
        self.logger.info("save_extracted_json", url=url)
        self.storage.save_extracted(url, data)

    def download(self, url: str) -> None:
        """Download and cache a binary document from the given URL."""
        if self.storage.document_exists(url):
            return

        self.logger.info("document_cache_miss", url=url)
        document = self.downloader(url)
        self.storage.save_document(document)
        self.logger.info("document_downloaded", url=url, size=len(document.content))

    def _snapshot_timestamp(self) -> str:
        """Return a UTC timestamp formatted for snapshot filenames."""
        return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H-%M-%S-%f")
