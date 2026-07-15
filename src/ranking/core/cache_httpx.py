from __future__ import annotations

import os
import re
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlparse

import httpx
import structlog

from ranking.core.cache import HttpClientWithCache
from ranking.core.errors import ExternalRedirectError

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
    ) -> None:
        """Initialize the cache with httpx as the fetcher."""
        super().__init__(
            plugin_name,
            cache_root=cache_root,
            normalize_for_comparison=normalize_for_comparison,
            save_extracted=save_extracted,
        )
        self.base_url = base_url
        self.document_root = Path(document_root)

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

    def download(self, url: str) -> Path:
        """Download and cache a binary document from the given URL."""
        key = self.derive_cache_key(url)
        shard = key[:2]
        parsed_url = urlparse(url)
        original_name = Path(parsed_url.path).name or "document"
        suffix = Path(original_name).suffix
        stem = Path(original_name).stem
        safe_stem = re.sub(r"[^A-Za-z0-9_]+", "_", stem) or "document"
        filename = f"{safe_stem}_{key}{suffix}"
        destination = self.document_root / self.plugin_name / shard / filename

        if destination.exists():
            self.logger.info("document_found_in_cache", url=url, path=destination)
            return destination

        self.logger.info("document_cache_miss", url=url, path=destination)
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

        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(response.content)
        self.logger.info(
            "document_downloaded", url=url, path=destination, size=len(response.content)
        )
        return destination

    @staticmethod
    def is_same_domain(url1: str, url2: str) -> bool:
        """Check if two URLs belong to the same domain."""
        return urlparse(url1).netloc == urlparse(url2).netloc
