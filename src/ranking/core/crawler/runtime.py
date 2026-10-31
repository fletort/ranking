from __future__ import annotations

import random
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable

import structlog

from ranking.core.storage import DownloadedDocument, LocalStorageProvider, StorageProvider


class CachePolicy(Enum):
    """Defines v1 cache behavior for each fetch call."""

    NO_CACHE = "NO_CACHE"
    CACHE_IF_PRESENT = "CACHE_IF_PRESENT"
    REFRESH_AND_CACHE = "REFRESH_AND_CACHE"


def default_is_temporary_unavailable_page(url: str, content: str) -> bool:
    """Default plugin hook implementation: never flag a page as temporarily unavailable.

    Plugins override this behavior by providing their own
    ``is_temporary_unavailable_page`` callable to :class:`CrawlerRuntime`. When a plugin
    does not implement the hook, the crawler keeps its existing behavior unchanged.
    """
    return False


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
        network_sleep_seconds: dict[str, int] = {"min": 1, "max": 3},
        normalize_for_comparison: Callable[[str, str], str] | None = None,
        is_temporary_unavailable_page: Callable[[str, str], bool] | None = None,
        save_extracted: bool = False,
        logger: Any = structlog.get_logger(),
        storage: StorageProvider | None = None,
    ) -> None:
        """Initialize a crawler instance scoped to a plugin name.

        Args:
            plugin_name: Logical name of the plugin owning this crawler instance.
            cache_root: Root directory for the local cache (used when *storage* is not provided).
            document_root: Root directory for downloaded documents
                           (used when *storage* is not provided).
            normalize_for_comparison: Optional hook to normalize content before change detection.
            is_temporary_unavailable_page: Optional plugin hook to detect a temporary
                maintenance page returned with a successful (2xx) HTTP status. It is used:

                - by :meth:`fetch` on **already cached** content: a flagged entry is not a
                  valid cache hit and is never snapshotted (it is refetched instead);
                - as a safety net by :meth:`fetch` on **freshly fetched** content: a flagged
                  response is rejected (``RuntimeError``) before any cache or snapshot write.

                Retrying flagged fresh content through the standard retry mechanism remains
                the responsibility of the ``fetcher`` implementation, which must not return
                flagged content (see :class:`HttpxCrawlerRuntime`). Defaults to
                :func:`default_is_temporary_unavailable_page` (never flags anything).
            save_extracted: If True, extracted JSON data is persisted via the storage provider.
            logger: Structured logger instance.
            storage: Storage provider to use. Defaults to
                :class:`~ranking.portinglayer.storage.LocalStorageProvider`.
        """
        self.plugin_name = plugin_name
        self.logger = logger
        self.save_extracted = save_extracted
        self.network_sleep_seconds = network_sleep_seconds
        self.sleep_duration_seconds = 0.0

        # Optional normalization hook (plugin-controlled)
        self.normalize_for_comparison = normalize_for_comparison

        # Optional plugin hook flagging a 2xx page that is actually a temporary maintenance
        # page. It is used by fetch() for cached content (flagged entries are invalidated and
        # never snapshotted) and as a safety net for freshly fetched content (flagged
        # responses are rejected before any write). Retrying belongs to the fetcher.
        self.is_temporary_unavailable_page = (
            is_temporary_unavailable_page or default_is_temporary_unavailable_page
        )

        self.cache_hits = 0
        self.cache_misses = 0

        if storage is None:
            storage = LocalStorageProvider(
                plugin_name, cache_root=cache_root, document_root=document_root
            )
        self.storage = storage

    @abstractmethod
    def fetcher(self, url: str) -> str:
        """Fetch a resource, without using the cache. This is the network-level fetcher.

        Implementations must not return content flagged by the plugin hook
        ``is_temporary_unavailable_page``: a freshly fetched temporary unavailable page must be
        retried through the standard retry mechanism instead. As a safety net, the base
        :meth:`fetch` rejects flagged content returned by a fetcher that does not apply the
        hook, so it never reaches the cache layer. See :class:`HttpxCrawlerRuntime` for the
        reference implementation.
        """
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

    def _reject_temporary_unavailable_page(self, url: str, content: str) -> None:
        """Reject freshly fetched content flagged as a temporary unavailable page.

        Safety net ensuring flagged content never reaches the cache layer, even when the
        ``fetcher`` implementation does not apply the hook itself. Retrying is not handled
        here: the standard retry mechanism belongs to the ``fetcher`` implementation (see
        :class:`HttpxCrawlerRuntime`).

        Raises:
            RuntimeError: When the content is flagged as a temporary unavailable page.
        """
        if self.is_temporary_unavailable_page(url, content):
            self.logger.error("temporary_unavailable_page", url=url)
            raise RuntimeError(f"Temporary unavailable page for URL: {url}")

    def fetch(self, url: str, cache_policy: CachePolicy) -> str:
        """Fetch content according to policy and update storage when needed.

        Cached entries flagged by the plugin hook ``is_temporary_unavailable_page`` (fake
        ``200 OK`` maintenance pages) are treated as poisoned: they are never returned as a
        cache hit, nor snapshotted, and are refetched instead so the cache self-heals.

        Freshly fetched content is defensively rejected through
        :meth:`_reject_temporary_unavailable_page` as a safety net, while retrying flagged
        fresh content remains the responsibility of the ``fetcher`` implementation.
        """
        if cache_policy is CachePolicy.NO_CACHE:
            self.logger.info("No cache policy, fetching directly", url=url)
            self._sleep_before_network()
            content = self.fetcher(url)
            self._reject_temporary_unavailable_page(url, content)
            return content

        existing_content = self.storage.get_http_cache(url)

        if cache_policy is CachePolicy.CACHE_IF_PRESENT:
            if existing_content is not None and not self.is_temporary_unavailable_page(
                url, existing_content
            ):
                self.cache_hits += 1
                self.logger.info("Cache hit", url=url)
                return existing_content

            # A cached entry flagged as a temporary maintenance page is a poisoned cache:
            # ignore it and refetch so the entry self-heals with the current content.
            if existing_content is not None:
                self.logger.warning("cache_temporary_unavailable_page", url=url)

            self.cache_misses += 1
            self.logger.info("Cache miss, fetching", url=url)
            self._sleep_before_network()
            content = self.fetcher(url)
            self._reject_temporary_unavailable_page(url, content)
            self.storage.save_http_cache(url, content)
            return content

        if cache_policy is CachePolicy.REFRESH_AND_CACHE:
            self.logger.info("Cache refresh", url=url)
            self._sleep_before_network()
            fetched_content = self.fetcher(url)
            self._reject_temporary_unavailable_page(url, fetched_content)

            if existing_content is None:
                self.logger.info("No existing content, writing current cache", url=url)
                self.storage.save_http_cache(url, fetched_content)
                return fetched_content

            if self.is_temporary_unavailable_page(url, existing_content):
                # The previously cached content is a maintenance page: discard it instead
                # of snapshotting it, and refresh the cache with the current content.
                self.logger.warning("cache_temporary_unavailable_page", url=url)
                self.storage.save_http_cache(url, fetched_content)
                return fetched_content

            if self._has_changed(url, existing_content, fetched_content):
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
        self._sleep_before_network()
        document = self.downloader(url)
        self.storage.save_document(document)
        self.logger.info("document_downloaded", url=url, size=len(document.content))

    def _snapshot_timestamp(self) -> str:
        """Return a UTC timestamp formatted for snapshot filenames."""
        return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H-%M-%S-%f")

    def _sleep_before_network(self) -> None:
        if self.network_sleep_seconds["min"] <= 0 or self.network_sleep_seconds["max"] <= 0:
            return
        sleep_duration = random.uniform(
            self.network_sleep_seconds["min"], self.network_sleep_seconds["max"]
        )
        time.sleep(sleep_duration)
        self.sleep_duration_seconds += sleep_duration
