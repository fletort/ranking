from __future__ import annotations

import os
import re
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlparse

import httpx
import structlog

from ranking.core.cache import HttpClientWithCache
from ranking.core.errors import ExternalRedirectError
from ranking.core.storage import DownloadedDocument, StorageProvider
from ranking.portinglayer.storage import LocalStorageProvider

VERIFY_SSL = os.getenv("ENV") != "dev"

HEADERS = {
    "User-Agent": "RankingBot/0.1 (contact: https://github.com/fletort/ranking)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br",
}
DOCUMENT_DOWNLOAD_TIMEOUT = 10.0


class HttpxClientWithCache(HttpClientWithCache):
    """HTTP cache backed by httpx for network fetching."""

    def __init__(
        self,
        plugin_name: str,
        cache_root: Path | str = ".cache",
        document_root: Path | str = ".document",
        normalize_for_comparison: Callable[[str, str], str] | None = None,
        save_extracted: bool = False,
        base_url: str | None = None,
        storage: StorageProvider | None = None,
    ) -> None:
        """Initialize the cache with httpx as the fetcher."""
        if storage is None:
            storage = LocalStorageProvider(
                plugin_name, cache_root=cache_root, document_root=document_root
            )
        super().__init__(
            plugin_name,
            cache_root=cache_root,
            normalize_for_comparison=normalize_for_comparison,
            save_extracted=save_extracted,
            storage=storage,
        )
        self.base_url = base_url

    def fetcher(self, url: str) -> str:
        """Fetch the HTML content of a page at the given URL using httpx.

        Args:
            url: The URL to fetch.

        Returns:
            The raw HTML content as a string.

        Raises:
            RuntimeError: On HTTP error status codes or network-level errors.
            ExternalRedirectError: If the final URL after redirects is outside the allowed base URL.
        """
        try:
            log = structlog.get_logger()
            log.info("Fetching URL", url=url)
            response = httpx.get(
                url, headers=HEADERS, follow_redirects=True, verify=VERIFY_SSL, timeout=10.0
            )
            response.raise_for_status()
            final_url = str(response.url)

            log.debug(
                "http_fetch",
                requested_url=url,
                final_url=final_url,
                status=response.status_code,
                size=len(response.text),
            )

            if final_url != url:
                if self.base_url and not self.is_same_domain(final_url, self.base_url):
                    log.debug(
                        "external_redirect_detected",
                        from_url=url,
                        to_url=final_url,
                    )
                    raise ExternalRedirectError(requested_url=url, final_url=final_url)
                else:
                    log.info(
                        "redirect_detected",
                        from_url=url,
                        to_url=final_url,
                    )

            return response.text
        except httpx.HTTPStatusError as e:
            log.error("HTTP error fetching URL", url=url, status_code=e.response.status_code)
            raise RuntimeError(f"HTTP error {e.response.status_code} for URL: {url}") from e
        except httpx.RequestError as e:
            log.error("Network error fetching URL", url=url, error=str(e))
            raise RuntimeError(f"Network error fetching URL: {url}") from e

    def downloader(self, url: str) -> DownloadedDocument:
        """Download a document from the given URL without touching the cache."""
        try:
            response = httpx.get(
                url,
                headers=HEADERS,
                follow_redirects=True,
                verify=VERIFY_SSL,
                timeout=DOCUMENT_DOWNLOAD_TIMEOUT,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            self.logger.error(
                "HTTP error downloading document", url=url, status_code=e.response.status_code
            )
            raise RuntimeError(f"HTTP error {e.response.status_code} for URL: {url}") from e
        except httpx.RequestError as e:
            self.logger.error("Network error downloading URL", url=url, error=str(e))
            raise RuntimeError(f"Network error downloading URL: {url}") from e

        filename = self.extract_filename(response)
        return DownloadedDocument(
            url=url,
            content=response.content,
            original_filename=filename,
            content_length=len(response.content),
            content_type=response.headers.get("content-type", "application/octet-stream"),
            downloaded_at=datetime.now(timezone.utc),
        )

    @staticmethod
    def is_same_domain(url1: str, url2: str) -> bool:
        """Check if two URLs belong to the same domain."""
        return urlparse(url1).netloc == urlparse(url2).netloc

    @staticmethod
    def extract_filename(response: httpx.Response) -> str:
        cd = response.headers.get("content-disposition", "")

        match = re.search(r"filename\*\s*=\s*UTF-8''([^;]+)", cd, re.I)
        if match:
            return unquote(match.group(1))

        match = re.search(r'filename\s*=\s*"([^"]+)"', cd, re.I)
        if match:
            return match.group(1)

        match = re.search(r"filename\s*=\s*([^;]+)", cd, re.I)
        if match:
            return match.group(1).strip()

        # fallback URL
        return Path(urlparse(str(response.url)).path).name or "document"
