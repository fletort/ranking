from __future__ import annotations

import os
import re
import time
from collections.abc import Callable, Iterable
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlparse

import httpx

from ranking.core.crawler.runtime import CrawlerRuntime, FetchedResource
from ranking.core.errors import ExternalRedirectError, LocalServerErrorException
from ranking.core.storage.provider import DownloadedDocument, StorageProvider
from ranking.core.url import canonicalize_url, validate_http_scheme

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

def normalize_url(url: str) -> str:
    """Validate *url* and return its canonical form before a network request.

    The scheme is checked first, so a URL that is not an absolute ``http(s)`` URL fails
    immediately, without any network access or retry. Normalization is then delegated to the
    single, shared :func:`ranking.core.url.canonicalize_url`, which the Storage layer also uses to
    compute Resource IDs: the URL requested on the network is therefore exactly the URL whose
    identity is stored in the cache.

    Raises:
        ValueError: When the URL does not use the ``http`` or ``https`` scheme.
    """
    validate_http_scheme(url)
    return canonicalize_url(url)


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
            ExternalRedirectError: If the final URL after redirects is outside the allowed base URL.
            ValueError: If the URL is not an absolute ``http(s)`` URL.
        """
        url = normalize_url(url)
        response = self._request_with_retry(
            url,
            timeout=HTTP_TIMEOUT,
            error_noun="fetching",
            event_prefix="http",
            body_reject_message="Temporary unavailable page for URL: {url}",
            on_status_error=self._classify_fetch_status_error,
            body_validator=self._accept_fetched_body,
        )

        final_url = str(response.url)
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

    def _sleep_before_retry(self, attempt: int, event: str, **context: object) -> int:
        """Wait for the next backoff delay and return the next attempt number.

        Shared by the three retry triggers (transient status code, transient network error and
        temporary unavailable page) so the exponential backoff schedule, the sleep accounting
        and the warning log are defined only once.

        Args:
            attempt: The current (1-based) attempt number.
            event: Structured log event emitted before sleeping.
            **context: Extra fields added to the log event (e.g. ``url``, ``status_code``).

        Returns:
            The next attempt number (``attempt + 1``).
        """
        delay_seconds = self._retry_delay_seconds(attempt)
        self.logger.warning(
            event,
            attempt=attempt,
            max_attempts=self.max_attempts,
            delay_seconds=delay_seconds,
            **context,
        )
        time.sleep(delay_seconds)
        self.sleep_duration_seconds += delay_seconds
        return attempt + 1

    def _request_with_retry(
        self,
        url: str,
        *,
        timeout: float,
        error_noun: str,
        event_prefix: str,
        body_reject_message: str = "Unusable response for URL: {url}",
        on_status_error: Callable[[str, httpx.HTTPStatusError], bool] | None = None,
        body_validator: Callable[[str, httpx.Response], bool] | None = None,
    ) -> httpx.Response:
        """GET ``url`` and return the response, retrying transient failures.

        Shared by :meth:`fetcher` (HTML pages) and :meth:`downloader` (documents) so both apply
        the exact same retry policy through the shared exponential backoff:

        - retryable HTTP status codes (``retryable_status_codes``), with an optional
          ``on_status_error`` hook to force a retry (e.g. the fetcher's 500 health check);
        - transient network failures (``httpx.TimeoutException``, ``httpx.NetworkError``);
        - at most ``max_attempts`` attempts over the shared backoff schedule.

        Args:
            url: The URL to request.
            timeout: Request timeout, in seconds.
            error_noun: Verb used in error messages, e.g. ``"fetching"`` or ``"downloading"``.
            event_prefix: Prefix of the structured-log events, e.g. ``"http"`` or ``"download"``.
            body_reject_message: Message raised when a rejected body outlives the retry budget.
                ``{url}`` is substituted with the requested URL.
            on_status_error: Optional callback invoked for every HTTP error status before the
                retry decision. Returning ``True`` forces a retry; it may raise to abort
                immediately (e.g. ``LocalServerErrorException`` for a localized page bug).
            body_validator: Optional callback invoked for every successful (2xx) response.
                Returning ``False`` rejects the body and retries it (e.g. a temporary
                maintenance page served as ``200 OK``); it may raise to abort immediately
                (e.g. ``ExternalRedirectError``).

        Returns:
            The accepted response.

        Raises:
            RuntimeError: On HTTP error status codes, rejected bodies or network-level errors,
                once retries are exhausted.
            Exception: Whatever ``on_status_error`` or ``body_validator`` raises.
        """
        attempt = 1
        while True:
            self.logger.info(f"{event_prefix}_request", url=url, attempt=attempt)
            try:
                response = httpx.get(
                    url,
                    headers=HEADERS,
                    follow_redirects=True,
                    verify=VERIFY_SSL,
                    timeout=timeout,
                )
                response.raise_for_status()
            except httpx.HTTPStatusError as e:
                status_code = e.response.status_code
                retryable = status_code in self.retryable_status_codes
                if on_status_error is not None:
                    retryable = on_status_error(url, e) or retryable

                if not retryable or attempt >= self.max_attempts:
                    self.logger.error(
                        f"{event_prefix}_error",
                        url=url,
                        status_code=status_code,
                        attempts=attempt,
                        retryable=retryable,
                    )
                    raise RuntimeError(f"HTTP error {status_code} for URL: {url}") from e

                attempt = self._sleep_before_retry(
                    attempt, f"{event_prefix}_transient_error", url=url, status_code=status_code
                )
            except (httpx.TimeoutException, httpx.NetworkError) as e:
                # Transient network-level failures (read/connect/write timeouts, connection
                # resets, DNS hiccups) feed the same retry/backoff loop as 5xx codes.
                if attempt >= self.max_attempts:
                    self.logger.error(
                        f"{event_prefix}_network_error",
                        url=url,
                        error=str(e),
                        attempts=attempt,
                        max_attempts=self.max_attempts,
                    )
                    raise RuntimeError(f"Network error {error_noun} URL: {url}") from e

                attempt = self._sleep_before_retry(
                    attempt, f"{event_prefix}_transient_network_error", url=url, error=str(e)
                )
            except httpx.RequestError as e:
                # Any other network-level error (e.g. too many redirects, invalid URL) is not
                # transient: fail immediately.
                self.logger.error(f"{event_prefix}_network_error", url=url, error=str(e))
                raise RuntimeError(f"Network error {error_noun} URL: {url}") from e
            else:
                if body_validator is not None and not body_validator(url, response):
                    if attempt >= self.max_attempts:
                        self.logger.error(
                            f"{event_prefix}_unacceptable_response",
                            url=url,
                            attempts=attempt,
                            max_attempts=self.max_attempts,
                        )
                        raise RuntimeError(body_reject_message.format(url=url))
                    attempt = self._sleep_before_retry(
                        attempt, f"{event_prefix}_unacceptable_response", url=url
                    )
                    continue
                return response

    def _classify_fetch_status_error(self, url: str, error: httpx.HTTPStatusError) -> bool:
        """Return ``True`` when a fetch status error must be retried.

        A server error that may be page-specific (500 by default, configurable through the
        ``RANKING_HTTP_HEALTH_CHECK_STATUS_CODES`` environment variable) first triggers a
        reference page (``CheckPage``) health check: a healthy reference page means the target
        URL is the only thing broken, so it fails immediately without retry
        (``LocalServerErrorException``); a down reference page means the whole website is
        unavailable, so the standard retry mechanism applies.
        """
        status_code = error.response.status_code
        if status_code not in self.health_check_status_codes:
            return False
        if self._is_reference_page_healthy(url):
            self.logger.error("http_local_server_error", url=url, status_code=status_code)
            raise LocalServerErrorException(requested_url=url, status_code=status_code) from error
        # Reference page is down too: the whole site is unavailable, retry.
        return True

    def _accept_fetched_body(self, url: str, response: httpx.Response) -> bool:
        """Return ``False`` to retry a 2xx response that is not the real page content.

        An external redirect (final URL outside the allowed ``base_url``) is fatal and raised
        here so it is never retried. A temporary maintenance page served as a fake ``200 OK``
        is rejected so it is retried and never cached nor snapshotted.
        """
        final_url = str(response.url)
        if final_url != url:
            if self.base_url and not self.is_same_domain(final_url, self.base_url):
                self.logger.debug("external_redirect_detected", from_url=url, to_url=final_url)
                raise ExternalRedirectError(requested_url=url, final_url=final_url)
            self.logger.info("redirect_detected", from_url=url, to_url=final_url)
        return not self.is_temporary_unavailable_page(url, response.text)

    def downloader(self, url: str) -> DownloadedDocument:
        """Download a document from the given URL without touching the cache.

        Transient failures (retryable status codes, read/connect timeouts and connection errors)
        are retried through the same backoff schedule as :meth:`fetcher`, via
        :meth:`_request_with_retry`.

        Raises:
            RuntimeError: On HTTP error status codes or network-level errors, once retries are
                exhausted.
            ValueError: If the URL is not an absolute ``http(s)`` URL.
        """
        url = normalize_url(url)
        response = self._request_with_retry(
            url,
            timeout=DOCUMENT_DOWNLOAD_TIMEOUT,
            error_noun="downloading",
            event_prefix="download",
        )

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
