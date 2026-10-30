from __future__ import annotations

import os
import re
import time
from collections.abc import Callable, Iterable
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlparse

import httpx
import structlog

from ranking.core.crawler.runtime import CrawlerRuntime
from ranking.core.errors import ExternalRedirectError, LocalServerErrorException
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
HEALTH_CHECK_STATUS_CODES_ENV = "RANKING_HTTP_HEALTH_CHECK_STATUS_CODES"
# Transient infrastructure failures (maintenance windows, gateway micro-outages).
DEFAULT_RETRYABLE_STATUS_CODES = (502, 503, 504)
# Server errors that may be page-specific (application bug) or site-wide (outage).
# When one of these codes is received, the runtime probes a reference page to tell both
# cases apart before deciding whether the URL is worth retrying.
DEFAULT_HEALTH_CHECK_STATUS_CODES = (500,)
# Exponential backoff schedule: the delay before attempt N is the item N-1 of this tuple.
# The last delay is reused when the schedule is shorter than the number of attempts.
DEFAULT_RETRY_DELAYS_SECONDS = (30.0, 60.0, 120.0, 300.0, 3600.0)


def _parse_status_codes(
    raw: str | None, *, default: tuple[int, ...], context: str
) -> tuple[int, ...]:
    """Parse a comma-separated list of HTTP status codes with a shared implementation.

    Args:
        raw: Raw value, e.g. ``"502,503,504"``. When empty or ``None``, *default* is returned.
        default: Value returned when *raw* is empty or ``None``.
        context: Name reported in error messages to locate the offending value.

    Returns:
        The status codes to use, in declaration order and without duplicates.

    Raises:
        ValueError: If a value is not a valid HTTP status code (100-599).
    """
    if raw is None or not raw.strip():
        return default

    codes: list[int] = []
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        try:
            code = int(item)
        except ValueError as e:
            raise ValueError(f"Invalid HTTP status code {item!r} in {context}") from e
        if code not in codes:
            codes.append(code)

    return validate_retryable_status_codes(codes, context=context)


def parse_retryable_status_codes(raw: str | None) -> tuple[int, ...]:
    """Parse a comma-separated list of HTTP status codes to retry on.

    Args:
        raw: Raw value, e.g. ``"502,503,504"``. When empty or ``None``,
            ``DEFAULT_RETRYABLE_STATUS_CODES`` is returned.

    Returns:
        The status codes to retry on, in declaration order and without duplicates.

    Raises:
        ValueError: If a value is not a valid HTTP status code (100-599).
    """
    return _parse_status_codes(
        raw, default=DEFAULT_RETRYABLE_STATUS_CODES, context=RETRYABLE_STATUS_CODES_ENV
    )


def parse_health_check_status_codes(raw: str | None) -> tuple[int, ...]:
    """Parse a comma-separated list of HTTP status codes triggering a reference page check.

    Args:
        raw: Raw value, e.g. ``"500"``. When empty or ``None``,
            ``DEFAULT_HEALTH_CHECK_STATUS_CODES`` is returned.

    Returns:
        The status codes to health-check, in declaration order and without duplicates.

    Raises:
        ValueError: If a value is not a valid HTTP status code (100-599).
    """
    return _parse_status_codes(
        raw, default=DEFAULT_HEALTH_CHECK_STATUS_CODES, context=HEALTH_CHECK_STATUS_CODES_ENV
    )


def validate_retryable_status_codes(
    codes: Iterable[int], *, context: str = RETRYABLE_STATUS_CODES_ENV
) -> tuple[int, ...]:
    """Validate HTTP status codes, whatever their source.

    Used for both the ``RANKING_HTTP_RETRY_STATUS_CODES`` value and the
    ``retryable_status_codes`` constructor argument, so both are checked the same way.

    Args:
        codes: Candidate status codes, in declaration order.
        context: Name reported in error messages to locate the offending value.

    Returns:
        The status codes as a tuple, in the given order.

    Raises:
        ValueError: If the sequence is empty, or contains a value that is not an
            HTTP status code (100-599).
    """
    validated: list[int] = []
    for code in codes:
        error_message = f"Invalid HTTP status code {code!r} in {context}"
        try:
            value = int(code)
        except (TypeError, ValueError) as e:
            raise ValueError(error_message) from e
        if not 100 <= value <= 599:
            raise ValueError(error_message)
        validated.append(value)

    if not validated:
        raise ValueError(f"No HTTP status code found in {context}: {codes!r}")

    return tuple(validated)


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
        try:
            delays.append(float(item))
        except ValueError as e:
            raise ValueError(f"Invalid retry delay {item!r} in {RETRY_DELAYS_ENV}") from e

    return validate_retry_delays_seconds(delays)


def validate_retry_delays_seconds(
    delays: Iterable[float], *, context: str = RETRY_DELAYS_ENV
) -> tuple[float, ...]:
    """Validate a backoff schedule, whatever its source.

    Used for both the ``RANKING_HTTP_RETRY_DELAYS_SECONDS`` value and the
    ``retry_delays_seconds`` constructor argument, so both are checked the same way.
    A delay that is negative or non-finite would be passed to ``time.sleep`` and
    break the retry loop, so it is rejected up front.

    Args:
        delays: Candidate delays, in seconds, in the order the retries happen.
        context: Name reported in error messages to locate the offending value.

    Returns:
        The delays as a tuple, in the given order.

    Raises:
        ValueError: If the sequence is empty, or contains a negative or
            non-finite (``nan``/``inf``) value.
    """
    validated: list[float] = []
    for delay in delays:
        error_message = f"Invalid retry delay {delay!r} in {context}"
        try:
            value = float(delay)
        except (TypeError, ValueError) as e:
            raise ValueError(error_message) from e
        if not 0 <= value < float("inf"):  # reject negative and non-finite values
            raise ValueError(error_message)
        validated.append(value)

    if not validated:
        raise ValueError(f"No retry delay found in {context}: {delays!r}")

    return tuple(validated)


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
        health_check_status_codes: tuple[int, ...] | None = None,
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
            health_check_status_codes: HTTP status codes that trigger a reference page
                (``CheckPage``) health check before deciding to retry. Defaults to the
                ``RANKING_HTTP_HEALTH_CHECK_STATUS_CODES`` environment variable, or to
                ``DEFAULT_HEALTH_CHECK_STATUS_CODES`` (``500``) when it is not set.

        Raises:
            ValueError: If ``retryable_status_codes``, ``retry_delays_seconds`` or
                ``health_check_status_codes`` are empty or contain invalid values, e.g. a
                negative or non-finite delay.
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
        # Last URL successfully fetched, used as a reference page for the health check.
        self._last_successful_url: str | None = None
        if retryable_status_codes is None:
            self.retryable_status_codes = parse_retryable_status_codes(
                os.getenv(RETRYABLE_STATUS_CODES_ENV)
            )
        else:
            self.retryable_status_codes = validate_retryable_status_codes(
                retryable_status_codes, context="retryable_status_codes"
            )

        if retry_delays_seconds is None:
            self.retry_delays_seconds = parse_retry_delays_seconds(os.getenv(RETRY_DELAYS_ENV))
        else:
            self.retry_delays_seconds = validate_retry_delays_seconds(
                retry_delays_seconds, context="retry_delays_seconds"
            )

        if health_check_status_codes is None:
            self.health_check_status_codes = parse_health_check_status_codes(
                os.getenv(HEALTH_CHECK_STATUS_CODES_ENV)
            )
        else:
            self.health_check_status_codes = validate_retryable_status_codes(
                health_check_status_codes, context="health_check_status_codes"
            )

        self.max_attempts = len(self.retry_delays_seconds) + 1

    def fetcher(self, url: str) -> str:
        """Fetch the HTML content of a page at the given URL using httpx.

        Transient infrastructure failures (502/503/504 by default, configurable through the
        ``RANKING_HTTP_RETRY_STATUS_CODES`` environment variable) are retried with an
        exponential backoff (configurable through the ``RANKING_HTTP_RETRY_DELAYS_SECONDS``
        environment variable). Other HTTP error status codes fail immediately.

        A server error that may be page-specific (500 by default, configurable through the
        ``RANKING_HTTP_HEALTH_CHECK_STATUS_CODES`` environment variable) first triggers a
        lightweight health check against a reference page (``CheckPage``): if that page still
        responds normally, the target URL has a localized bug and fails immediately without
        retry (``LocalServerErrorException``); if the reference page is also down, the whole
        website is considered unavailable and the standard retry mechanism applies.

        Args:
            url: The URL to fetch.

        Returns:
            The raw HTML content as a string.

        Raises:
            RuntimeError: On HTTP error status codes or network-level errors.
            LocalServerErrorException: When the target returns a health-check status code but the
                reference page is healthy (localized page bug, no retry).
            ExternalRedirectError: If the final URL after redirects is outside the allowed base URL.
        """
        attempt = 1
        while True:
            try:
                content = self._fetch_once(url)
            except httpx.HTTPStatusError as e:
                status_code = e.response.status_code
                retryable = status_code in self.retryable_status_codes

                # Distinguish a localized page bug (500) from a global site outage before
                # entering the retry loop: a healthy reference page means the target URL is the
                # only thing broken, so retrying it would only block the crawler queue.
                if status_code in self.health_check_status_codes:
                    if self._is_reference_page_healthy(url):
                        self.logger.error(
                            "http_local_server_error",
                            url=url,
                            status_code=status_code,
                            attempts=attempt,
                        )
                        raise LocalServerErrorException(
                            requested_url=url, status_code=status_code
                        ) from e
                    # Reference page is down too: the whole site is unavailable, retry.
                    retryable = True

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
            else:
                self._last_successful_url = url
                return content

    def _reference_page_url(self, url: str) -> str | None:
        """Return the reference page (``CheckPage``) to probe for a site health check.

        Preference order:

        1. the last successfully fetched page, when one is known;
        2. the configured ``base_url`` (the website's known entry page);
        3. the root domain of the requested URL, as a last resort.
        If any of the above options are not applicable, return ``None``.
        """
        if self._last_successful_url and self._last_successful_url != url:
            return self._last_successful_url
        if self.base_url and self.base_url != url:
            return self.base_url
        parsed = urlparse(url)
        root = f"{parsed.scheme}://{parsed.netloc}/"
        if root != url:
            return root
        return None

    def _is_reference_page_healthy(self, url: str) -> bool:
        """Return ``True`` when the reference page responds without a server error.

        A network-level failure or a 5xx response means the website itself is down, so the
        target error is not a localized page bug.
        """
        check_url = self._reference_page_url(url)
        if not check_url:
            self.logger.warning("http_health_check_unavailable", url=url)
            return False
        self.logger.info("http_health_check", url=url, check_url=check_url)
        try:
            with httpx.stream(
                "GET",
                check_url,
                headers=HEADERS,
                follow_redirects=True,
                verify=VERIFY_SSL,
                timeout=HTTP_TIMEOUT,
            ) as response:
                # Only the status is needed, so the page body is never downloaded.
                status_code = response.status_code
        except httpx.RequestError as e:
            self.logger.warning(
                "http_health_check_unreachable", url=url, check_url=check_url, error=str(e)
            )
            return False
        return status_code < 500

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
