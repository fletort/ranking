"""Parsing and validation of the HTTP retry configuration.

Both the environment variables (``RANKING_HTTP_RETRY_STATUS_CODES``,
``RANKING_HTTP_RETRY_DELAYS_SECONDS``, ``RANKING_HTTP_HEALTH_CHECK_STATUS_CODES``) and the
equivalent constructor arguments go through the same helpers here, so every source is checked
identically. Kept out of :mod:`ranking.core.crawler.httpx` so the crawler runtime stays focused
on the fetch lifecycle.

This module has no dependency on httpx: it only deals with plain status codes and delays.
"""

from __future__ import annotations

from collections.abc import Iterable

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
