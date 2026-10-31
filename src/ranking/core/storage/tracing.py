from __future__ import annotations

from typing import Any

import structlog

from ranking.core.storage.identity import compute_resource_id
from ranking.core.storage.provider import (
    DownloadedDocument,
    HealthCheckResult,
    StorageProvider,
)


class TracingStorageProvider(StorageProvider):
    """StorageProvider decorator emitting a structured trace on each write.

    It wraps another :class:`StorageProvider` and delegates every operation to it,
    adding a single observability concern: a structured log entry emitted after a
    successful write, including the deterministic ``resource_id`` derived from the
    target URL.

    Trace format (as rendered by structlog)::

        http_cache_saved
        url=https://...
        resource_id=1c4230...

    The wrapped provider stays unchanged and remains responsible for identity,
    layout and persistence. This decorator is opt-in and can be wired at
    construction time (see ``ranking.cli.build_cache``).
    """

    def __init__(self, provider: StorageProvider, logger: Any = None) -> None:
        """Wrap *provider*, emitting traces through *logger*.

        Args:
            provider: The storage provider to delegate to.
            logger: Structured logger instance. Defaults to a structlog logger
                bound with ``component="storage"``.
        """
        super().__init__(provider.plugin_name)
        self._provider = provider
        self._logger = logger or structlog.get_logger().bind(component="storage")

    def _trace(self, event: str, url: str) -> None:
        """Emit a structured storage trace for *url*."""
        self._logger.info(event, url=url, resource_id=compute_resource_id(url))

    def save_http_cache(self, url: str, content: str) -> None:
        self._provider.save_http_cache(url, content)
        self._trace("http_cache_saved", url)

    def get_http_cache(self, url: str) -> str | None:
        return self._provider.get_http_cache(url)

    def exists_http_cache(self, url: str) -> bool:
        return self._provider.exists_http_cache(url)

    def save_http_snapshot(self, url: str, content: str, timestamp: str) -> None:
        self._provider.save_http_snapshot(url, content, timestamp)

    def list_http_snapshots(self, url: str) -> list[tuple[str, str]]:
        return self._provider.list_http_snapshots(url)

    def save_extracted(self, url: str, data: Any) -> None:
        self._provider.save_extracted(url, data)

    def get_extracted(self, url: str) -> Any:
        return self._provider.get_extracted(url)

    def save_document(self, document: DownloadedDocument) -> None:
        self._provider.save_document(document)

    def get_document(self, url: str) -> DownloadedDocument | None:
        return self._provider.get_document(url)

    def document_exists(self, url: str) -> bool:
        return self._provider.document_exists(url)

    def healthcheck(self) -> HealthCheckResult:
        return self._provider.healthcheck()


__all__ = ["TracingStorageProvider"]
