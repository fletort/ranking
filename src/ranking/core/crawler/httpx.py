from __future__ import annotations

import os
import re
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlparse

import httpx
import structlog

from ranking.core.crawler.runtime import CrawlerRuntime
from ranking.core.errors import ExternalRedirectError
from ranking.core.storage.provider import DownloadedDocument, StorageProvider

VERIFY_SSL = os.getenv("ENV") != "dev"

HEADERS = {
    "User-Agent": "RankingBot/0.1 (contact: https://github.com/fletort/ranking)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br",
}
HTTP_TIMEOUT = 10.0
DOCUMENT_DOWNLOAD_TIMEOUT = 10.0

RETRYABLE_STATUS_CODES_ENV = "RANKING_HTTP_RETRY_STATUS_CODES"
RETRY_DELAYS_ENV = "RANKING_HTTP_RETRY_DELAYS_SECONDS"
# Transient infrastructure failures (maintenance windows, gateway micro-outages).
DEFAULT_RETRYABLE_STATUS_CODES = (502, 503, 504)
# Exponential backoff schedule: the delay before attempt N is the item N-1 of this tuple.
# The last delay is reused when the schedule is shorter than the number of attempts.
DEFAULT_RETRY_DELAYS_SECONDS = (30.0, 60.0, 120.0, 300.0, 3600.0)


def parse_retryable_status_codes(raw: str | None) -> tuple[int, ...]:
    """Parse a comma-separated list of HTTP status codes.

    Args:
        raw: Raw value, e.g. ``"502,503,504"``. When empty or ``None``,
            ``DEFAULT_RETRYABLE_STATUS_CODES`` is returned.

    Returns:
        The status codes to retry on, in declaration order and without duplicates.

    Raises:
        ValueError: If a value is not a valid HTTP status code (100-599).
    """
    if raw is None or not raw.strip():
        return DEFAULT_RETRYABLE_STATUS_CODES

    codes: list[int] = []
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        error_message = f"Invalid HTTP status code {item!r} in {RETRYABLE_STATUS_CODES_ENV}"
        try:
            code = int(item)
        except ValueError as e:
            raise ValueError(error_message) from e
        if not 100 <= code <= 599:
            raise ValueError(error_message)
        if code not in codes:
            codes.append(code)

    if not codes:
        raise ValueError(f"No HTTP status code found in {RETRYABLE_STATUS_CODES_ENV}: {raw!r}")

    return tuple(codes)


def parse_retry_delays_seconds(raw: str | None) -> tuple[float, ...]:
    """Parse a comma-separated list of backoff delays, in seconds.

    Args:
        raw: Raw value, e.g. ``"30,60,120"``. When empty or ``None``,
            ``DEFAULT_RETRY_DELAYS_SECONDS`` is returned.

    Returns:
        The backoff delays, in the order the retries happen:
        the item ``N - 1`` is the delay before attempt ``N``.

    Raises:
        ValueError: If a value is not a non-negative number of seconds.
    """
    if raw is None or not raw.strip():
        return DEFAULT_RETRY_DELAYS_SECONDS

    delays: list[float] = []
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        error_message = f"Invalid retry delay {item!r} in {RETRY_DELAYS_ENV}"
        try:
            delay = float(item)
        except ValueError as e:
            raise ValueError(error_message) from e
        if not 0 <= delay < float("inf"):  # reject negative and non-finite values
            raise ValueError(error_message)
        delays.append(delay)

    if not delays:
        raise ValueError(f"No retry delay found in {RETRY_DELAYS_ENV}: {raw!r}")

    return tuple(delays)


class HttpxCrawlerRuntime(CrawlerRuntime):
    """Crawler runtime implementation using httpx for network operations."""

    def __init__(
        self,
        plugin_name: str,
        cache_root: Path | str = ".cache",
        document_root: Path | str = ".document",
        network_sleep_seconds: dict[str, int] = {"min": 1, "max": 3},
        normalize_for_comparison: Callable[[str, str], str] | None = None,
        save_extracted: bool = False,
        base_url: str | None = None,
        storage: StorageProvider | None = None,
        retryable_status_codes: tuple[int, ...] | None = None,
        retry_delays_seconds: tuple[float, ...] | None = None,
    ) -> None:
        """Initialize the cache with httpx as the fetcher.

        Args:
            retryable_status_codes: HTTP status codes triggering a retry of the fetch.
                Defaults to the ``RANKING_HTTP_RETRY_STATUS_CODES`` environment variable,
                or to ``DEFAULT_RETRYABLE_STATUS_CODES`` when it is not set.
            retry_delays_seconds: Backoff schedule, in seconds; the delay before attempt N
                is item N-1. Defaults to the ``RANKING_HTTP_RETRY_DELAYS_SECONDS``
                environment variable, or to ``DEFAULT_RETRY_DELAYS_SECONDS`` when it is not set.
                At most ``len(retry_delays_seconds) + 1`` attempts are made.
        """
        super().__init__(
            plugin_name,
            cache_root=cache_root,
            document_root=document_root,
            network_sleep_seconds=network_sleep_seconds,
            normalize_for_comparison=normalize_for_comparison,
            save_extracted=save_extracted,
            storage=storage,
        )
        self.base_url = base_url
        if retryable_status_codes is None:
            retryable_status_codes = parse_retryable_status_codes(
                os.getenv(RETRYABLE_STATUS_CODES_ENV)
            )
        self.retryable_status_codes = tuple(retryable_status_codes)
        if retry_delays_seconds is None:
            retry_delays_seconds = parse_retry_delays_seconds(os.getenv(RETRY_DELAYS_ENV))
        self.retry_delays_seconds = tuple(retry_delays_seconds)
        self.max_attempts = len(self.retry_delays_seconds) + 1

    def fetcher(self, url: str) -> str:
        """Fetch the HTML content of a page at the given URL using httpx.

        Transient infrastructure failures (502/503/504 by default, configurable through the
        ``RANKING_HTTP_RETRY_STATUS_CODES`` environment variable) are retried with an
        exponential backoff (configurable through the ``RANKING_HTTP_RETRY_DELAYS_SECONDS``
        environment variable). Other HTTP error status codes fail immediately.

        Args:
            url: The URL to fetch.

        Returns:
            The raw HTML content as a string.

        Raises:
            RuntimeError: On HTTP error status codes or network-level errors.
            ExternalRedirectError: If the final URL after redirects is outside the allowed base URL.
        """
        attempt = 1
        while True:
            try:
                return self._fetch_once(url)
            except httpx.HTTPStatusError as e:
                status_code = e.response.status_code
                retryable = status_code in self.retryable_status_codes
                if not retryable or attempt >= self.max_attempts:
                    self.logger.error(
                        "HTTP error fetching URL",
                        url=url,
                        status_code=status_code,
                        attempts=attempt,
                        retryable=retryable,
                    )
                    raise RuntimeError(f"HTTP error {status_code} for URL: {url}") from e

                delay_seconds = self._retry_delay_seconds(attempt)
                self.logger.warning(
                    "http_transient_error",
                    url=url,
                    status_code=status_code,
                    attempt=attempt,
                    max_attempts=self.max_attempts,
                    delay_seconds=delay_seconds,
                )
                time.sleep(delay_seconds)
                self.sleep_duration_seconds += delay_seconds
                attempt += 1

    def _retry_delay_seconds(self, attempt: int) -> float:
        """Return the backoff delay before the next attempt (``attempt`` is 1-based)."""
        index = min(attempt - 1, len(self.retry_delays_seconds) - 1)
        return self.retry_delays_seconds[index]

    def _fetch_once(self, url: str) -> str:
        """Perform a single HTTP request and validate its response.

        Raises:
            httpx.HTTPStatusError: On HTTP error status codes.
            httpx.RequestError: On network-level errors.
            ExternalRedirectError: If the final URL after redirects is outside the allowed base URL.
        """
        log = structlog.get_logger()
        log.info("Fetching URL", url=url)
        try:
            response = httpx.get(
                url, headers=HEADERS, follow_redirects=True, verify=VERIFY_SSL, timeout=HTTP_TIMEOUT
            )
        except httpx.RequestError as e:
            log.error("Network error fetching URL", url=url, error=str(e))
            raise RuntimeError(f"Network error fetching URL: {url}") from e

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
