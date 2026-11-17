from __future__ import annotations

import os
import re
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlparse

import httpx

from ranking.core.crawler.retry_config import (
    HEALTH_CHECK_STATUS_CODES_ENV,
    RETRY_DELAYS_ENV,
    RETRYABLE_STATUS_CODES_ENV,
    parse_health_check_status_codes,
    parse_retry_delays_seconds,
    parse_retryable_status_codes,
    validate_retry_delays_seconds,
    validate_retryable_status_codes,
)
from ranking.core.crawler.runtime import CrawlerRuntime, FetchedResource
from ranking.core.errors import ExternalRedirectError, LocalServerErrorException
from ranking.core.storage.provider import DownloadedDocument, StorageProvider
from ranking.core.url import validate_http_scheme

VERIFY_SSL = os.getenv("ENV") != "dev"

HEADERS = {
    "User-Agent": "RankingBot/0.1 (contact: https://github.com/fletort/ranking)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br",
}
# Relaxed read timeout: slow legacy servers must not be aborted by httpx's 5s default.
HTTP_TIMEOUT = 20.0
DOCUMENT_DOWNLOAD_TIMEOUT = 20.0


class _RetryableTransportError(Exception):
    """Internal signal: a transient transport failure that the caller may retry.

    Raised by :meth:`HttpxCrawlerRuntime._send_get` for ``httpx.TimeoutException`` and
    ``httpx.NetworkError`` so both retry loops (HTML pages and documents) can back off and
    retry. The original exception is kept as :attr:`__cause__` for logging and error chaining.
    """


class HttpxCrawlerRuntime(CrawlerRuntime):
    """Crawler runtime implementation using httpx for network operations."""

    def __init__(
        self,
        plugin_name: str,
        cache_root: Path | str = ".cache",
        document_root: Path | str = ".document",
        network_sleep_seconds: dict[str, int] = {"min": 1, "max": 3},
        normalize_for_comparison: Callable[[str, str], str] | None = None,
        is_temporary_unavailable_page: Callable[[str, str], bool] | None = None,
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
            is_temporary_unavailable_page: Optional plugin hook detecting a temporary
                maintenance page served with a successful (2xx) status. When it returns
                ``True``, the page is neither cached nor snapshotted and the fetch is
                retried through the standard retry mechanism. Defaults to
                :func:`~ranking.core.crawler.runtime.default_is_temporary_unavailable_page`.

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
            is_temporary_unavailable_page=is_temporary_unavailable_page,
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
        self.attempt = 0

    def fetcher(self, url: str) -> FetchedResource:
        """Fetch the HTML content of a page at the given URL using httpx.

        Transient infrastructure failures (502/503/504 by default, configurable through the
        ``RANKING_HTTP_RETRY_STATUS_CODES`` environment variable) are retried with an
        exponential backoff (configurable through the ``RANKING_HTTP_RETRY_DELAYS_SECONDS``
        environment variable). Other HTTP error status codes fail immediately.

        Transient network-level errors (``httpx.TimeoutException`` and ``httpx.NetworkError``,
        i.e. read/connect/write timeouts, connection resets or DNS hiccups) feed the same retry
        loop, so a single slow response no longer aborts the whole crawl. Requests use an explicit,
        relaxed timeout (``HTTP_TIMEOUT``, 20s) instead of httpx's 5s default. Other network errors
        (e.g. too many redirects, invalid URL) still fail immediately.

        A server error that may be page-specific (500 by default, configurable through the
        ``RANKING_HTTP_HEALTH_CHECK_STATUS_CODES`` environment variable) first triggers a
        lightweight health check against a reference page (``CheckPage``): if that page still
        responds normally, the target URL has a localized bug and fails immediately without
        retry (``LocalServerErrorException``); if the reference page is also down, the whole
        website is considered unavailable and the standard retry mechanism applies.

        A temporary maintenance page served with a successful (2xx) status (e.g. a fake
        ``200 OK`` displaying "On revient très vite !") is detected by the plugin hook
        ``is_temporary_unavailable_page``. When flagged, the content is never cached nor
        snapshotted, and the request is retried through the same standard retry mechanism.

        Args:
            url: The URL to fetch.

        Returns:
            The raw HTML content and the final URL after redirects, as a
            :class:`~ranking.core.crawler.runtime.FetchedResource`.

        Raises:
            RuntimeError: On HTTP error status codes or network-level errors.
            LocalServerErrorException: When the target returns a health-check status code but the
                reference page is healthy (localized page bug, no retry).
            ExternalRedirectError: If the requested URL, or the final URL after redirects, is
                outside the allowed base URL.
            ValueError: If the URL is not an absolute ``http(s)`` URL.
        """
        validate_http_scheme(url)
        self._ensure_allowed_host(url)

        self.attempt = 1
        while True:
            self.logger.info("http_request", url=url, attempt=self.attempt)
            try:
                response = self._send_get(url, HTTP_TIMEOUT, "fetching", "http")
                response.raise_for_status()
            except _RetryableTransportError as transient_error:
                # Transient network-level failure: back off and retry.
                self._manage_retryable_transport_error(transient_error, url, "fetching", "http")
                continue
            except httpx.HTTPStatusError as e:
                self._manage_status_code_error(e, url, "http")
                continue

            # 2xx: keep the domain decisions explicit so the whole lifecycle is readable.
            final_url = str(response.url)
            if final_url != url:
                if self.base_url and not self.is_same_domain(final_url, self.base_url):
                    self.logger.debug("external_redirect_detected", from_url=url, to_url=final_url)
                    raise ExternalRedirectError(requested_url=url, final_url=final_url)
                self.logger.info("redirect_detected", from_url=url, to_url=final_url)

            if self.is_temporary_unavailable_page(url, response.text):
                # A fake 200 OK maintenance page: never cache it, retry instead.
                self._manage_temporary_unavailable_page(url, "http")
                continue

            self.logger.debug(
                "http_fetch",
                requested_url=url,
                final_url=final_url,
                status=response.status_code,
                size=len(response.text),
            )
            self._last_successful_url = url
            return FetchedResource(requested_url=url, final_url=final_url, content=response.text)

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

    def _sleep_before_retry(self, event: str, **context: object) -> None:
        """Wait for the next backoff delay and return the next attempt number.

        Shared by the three retry triggers (transient status code, transient network error and
        temporary unavailable page) so the exponential backoff schedule, the sleep accounting
        and the warning log are defined only once.

        Args:
            event: Structured log event emitted before sleeping.
            **context: Extra fields added to the log event (e.g. ``url``, ``status_code``).
        """
        delay_seconds = self._retry_delay_seconds(self.attempt)
        self.logger.warning(
            event,
            attempt=self.attempt,
            max_attempts=self.max_attempts,
            delay_seconds=delay_seconds,
            **context,
        )
        time.sleep(delay_seconds)
        self.sleep_duration_seconds += delay_seconds
        self.attempt += 1

    def _manage_retryable_transport_error(
        self, e: Exception, url: str, error_noun: str, event_prefix: str
    ) -> None:
        """Manage a retryable transport error.

        Logs the error and either raises a RuntimeError if the maximum number of attempts
        has been reached, or sleeps before retrying.

        Args:
            e: The exception that occurred.
            url: The URL being accessed when the error occurred.
            error_noun: Verb used in the fatal network-error message, e.g. ``"fetching"``.
            event_prefix: Prefix of the structured-log events, e.g. ``"http"`` or ``"download"``.
        Raises:
            RuntimeError: If the maximum number of attempts has been reached.
        """
        if self.attempt >= self.max_attempts:
            self.logger.error(
                f"{event_prefix}_network_error",
                url=url,
                error=str(e),
                attempts=self.attempt,
                max_attempts=self.max_attempts,
            )
            raise RuntimeError(f"Network error {error_noun} URL: {url}") from e
        self._sleep_before_retry(
            "http_transient_network_error",
            url=url,
            error=str(e),
        )

    def _manage_status_code_error(self, e: httpx.HTTPStatusError, url: str, event_prefix: str):
        """Manage an HTTP status code error.

        Logs the error and either raises a RuntimeError if the maximum number of attempts
        has been reached, or sleeps before retrying.

        Args:
            e: The HTTP status error that occurred.
            url: The URL being accessed when the error occurred.
            event_prefix: Prefix of the structured-log events, e.g. ``"http"`` or ``"download"``.
        Raises:
            RuntimeError: If the maximum number of attempts has been reached.
            LocalServerErrorException: If a local server error is detected and the reference page is
            healthy.
        """
        status_code = e.response.status_code if e.response else None
        retryable = status_code in self.retryable_status_codes
        if status_code in self.health_check_status_codes:
            # A page-specific server error (500 by default): probe a reference page.
            if self._is_reference_page_healthy(url):
                self.logger.error("http_local_server_error", url=url, status_code=status_code)
                raise LocalServerErrorException(requested_url=url, status_code=status_code) from e
            # The reference page is down too: the whole site is unavailable, retry.
            retryable = True
        if not retryable or self.attempt >= self.max_attempts:
            self.logger.error(
                f"{event_prefix}_error",
                url=url,
                status_code=status_code,
                attempts=self.attempt,
                retryable=retryable,
            )
            raise RuntimeError(f"HTTP error {status_code} for URL: {url}") from e
        self._sleep_before_retry(
            f"{event_prefix}_transient_error", url=url, status_code=status_code
        )

    def _manage_temporary_unavailable_page(self, url: str, event_prefix: str) -> None:
        """Manage temporary unavailable page scenarios.
        Args:
            url: The URL of the temporarily unavailable page.
            event_prefix: Prefix of the structured-log events, e.g. ``"http"`` or ``"download"``.
        Raises:
            RuntimeError: If the page remains temporarily unavailable after the maximum number of attempts.
        """
        if self.attempt >= self.max_attempts:
            self.logger.error(
                f"{event_prefix}_unacceptable_response",
                url=url,
                attempts=self.attempt,
                max_attempts=self.max_attempts,
            )
            raise RuntimeError(f"Temporary unavailable page for URL: {url}")
        self._sleep_before_retry(f"{event_prefix}_unacceptable_response", url=url)

    def _send_get(
        self, url: str, timeout: float, error_noun: str, event_prefix: str
    ) -> httpx.Response:
        """Perform a single ``httpx.get`` request and normalise transport failures.

        Low-level building block shared by :meth:`fetcher` and :meth:`downloader`. It only
        handles the transport layer: the HTTP status code is returned untouched so the callers
        keep their domain decisions (which status codes to retry, health checks, page
        validation) explicit in their own loops.

        A transient transport failure (``httpx.TimeoutException`` or ``httpx.NetworkError``,
        i.e. read/connect/write timeouts, connection resets or DNS hiccups) is translated into
        :class:`_RetryableTransportError` so the caller can back off and retry. Any other
        transport failure (e.g. too many redirects, invalid URL) is not transient and fails
        immediately with ``RuntimeError``.

        Args:
            url: The URL to request.
            timeout: Request timeout, in seconds.
            error_noun: Verb used in the fatal network-error message, e.g. ``"fetching"``.
            event_prefix: Prefix of the structured-log events, e.g. ``"http"`` or ``"download"``.

        Returns:
            The raw response, whatever its status code.

        Raises:
            _RetryableTransportError: On a transient transport failure.
            RuntimeError: On a non-transient transport failure.
        """
        try:
            return httpx.get(
                url,
                headers=HEADERS,
                follow_redirects=True,
                verify=VERIFY_SSL,
                timeout=timeout,
            )
        except (httpx.TimeoutException, httpx.NetworkError) as e:
            # Transient network-level failures (read/connect/write timeouts, connection resets,
            # DNS hiccups) are reported as retryable so the caller can back off and retry.
            raise _RetryableTransportError(str(e)) from e
        except httpx.RequestError as e:
            # Any other network-level error (e.g. too many redirects, invalid URL) is not
            # transient: fail immediately.
            self.logger.error(f"{event_prefix}_network_error", url=url, error=str(e))
            raise RuntimeError(f"Network error {error_noun} URL: {url}") from e

    def _ensure_allowed_host(self, url: str) -> None:
        """Refuse a URL whose host is outside the configured ``base_url``, before any request.

        Page-provided links may be absolute (``https://other``) or scheme-relative (``//other``);
        once resolved they replace the configured host. :meth:`fetcher` only checks the domain
        when the server redirects, so without this guard a *direct* request to another host would
        succeed and be cached. Raising :class:`ExternalRedirectError` here keeps the
        crawl on the configured site and lets the CLI skip the link
        (``event_skipped`` / ``race_skipped``).

        No-op when no ``base_url`` is configured.
        """
        if self.base_url and not self.is_same_domain(url, self.base_url):
            self.logger.debug("external_host_blocked", url=url, base_url=self.base_url)
            raise ExternalRedirectError(requested_url=url, final_url=url)

    def downloader(self, url: str) -> DownloadedDocument:
        """Download a document from the given URL without touching the cache.

        Transient failures (retryable status codes, read/connect timeouts and connection errors)
        are retried through the same backoff schedule as :meth:`fetcher`.

        Raises:
            RuntimeError: On HTTP error status codes or network-level errors, once retries are
                exhausted.
            ExternalRedirectError: If the URL is outside the allowed base URL.
            ValueError: If the URL is not an absolute ``http(s)`` URL.
        """
        validate_http_scheme(url)
        self._ensure_allowed_host(url)

        self.attempt = 1
        while True:
            self.logger.info("download_request", url=url, attempt=self.attempt)
            try:
                response = self._send_get(url, DOCUMENT_DOWNLOAD_TIMEOUT, "downloading", "download")
                response.raise_for_status()
            except _RetryableTransportError as transient_error:
                # Transient network-level failure: back off and retry.
                self._manage_retryable_transport_error(
                    transient_error, url, "downloading", "download"
                )
                continue
            except httpx.HTTPStatusError as e:
                self._manage_status_code_error(e, url, "download")
                continue
            break

        # Temporary unavailable page check (fake 200 OK maintenance page)
        content_type = response.headers.get("content-type", "").lower()
        start = response.content[:500].lower()
        is_html = "text/html" in content_type or b"<html" in start or b"<!doctype" in start
        if is_html and self.is_temporary_unavailable_page(url, response.text):
            self._manage_temporary_unavailable_page(url, "download")

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
        """Return True when both URLs share the same host and effective port.

        Hostnames are compared case-insensitively (DNS hostnames are), so ``https://EXAMPLE.COM/a``
        and ``https://example.com/b`` are the same site, while a different explicit port
        (``https://example.com:8443``) is not. A URL that cannot be parsed is never the same domain.
        """
        host1 = HttpxCrawlerRuntime._host_and_port(url1)
        host2 = HttpxCrawlerRuntime._host_and_port(url2)
        return host1 is not None and host1 == host2

    @staticmethod
    def _host_and_port(url: str) -> tuple[str, int | None] | None:
        """Return the normalized ``(hostname, port)`` of *url*, or ``None`` when unparseable."""
        try:
            parsed = urlparse(url)
            port = parsed.port
        except ValueError:
            # e.g. malformed IPv6 literal or invalid port.
            return None
        if not parsed.hostname:
            return None
        return (parsed.hostname.lower(), port)

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
