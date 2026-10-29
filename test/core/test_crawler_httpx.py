from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from pytest_httpx import HTTPXMock

import ranking.core.crawler.httpx as httpx_module
from ranking.core.crawler.httpx import (
    DEFAULT_RETRY_DELAYS_SECONDS,
    DEFAULT_RETRYABLE_STATUS_CODES,
    HEADERS,
    RETRY_DELAYS_ENV,
    RETRYABLE_STATUS_CODES_ENV,
    HttpxCrawlerRuntime,
    parse_retry_delays_seconds,
    parse_retryable_status_codes,
    validate_retry_delays_seconds,
    validate_retryable_status_codes,
)
from ranking.core.errors import ExternalRedirectError
from ranking.core.storage.provider import DownloadedDocument, HealthCheckResult, StorageProvider


def test_httpx_fetcher_returns_html(httpx_mock: HTTPXMock, tmp_path: Path) -> None:
    url = "https://example.com/page"
    httpx_mock.add_response(url=url, text="<html>Hello</html>")

    client = HttpxCrawlerRuntime("demo", tmp_path)
    result = client.fetcher(url)

    assert result == "<html>Hello</html>"


def test_httpx_fetcher_sends_custom_headers(httpx_mock: HTTPXMock, tmp_path: Path) -> None:
    url = "https://example.com/page"
    httpx_mock.add_response(url=url, text="ok")

    client = HttpxCrawlerRuntime("demo", tmp_path)
    client.fetcher(url)

    requests = httpx_mock.get_requests()
    assert len(requests) == 1
    for header, value in HEADERS.items():
        assert requests[0].headers.get(header) == value


def test_httpx_fetcher_raises_on_http_error(httpx_mock: HTTPXMock, tmp_path: Path) -> None:
    url = "https://example.com/not-found"
    httpx_mock.add_response(url=url, status_code=404)

    client = HttpxCrawlerRuntime("demo", tmp_path)
    with pytest.raises(RuntimeError, match="HTTP error 404"):
        client.fetcher(url)


def test_httpx_fetcher_raises_on_network_error(httpx_mock: HTTPXMock, tmp_path: Path) -> None:
    url = "https://example.com/fail"
    httpx_mock.add_exception(httpx.ConnectError("connection refused"), url=url)

    client = HttpxCrawlerRuntime("demo", tmp_path)
    with pytest.raises(RuntimeError, match="Network error fetching URL"):
        client.fetcher(url)


# ---------------------------------------------------------------------------
# Transient HTTP error retries (exponential backoff)
# ---------------------------------------------------------------------------

RETRYABLE_CODES = (502, 503, 504)
RETRY_BACKOFF = (30.0, 60.0, 120.0, 300.0, 3600.0)


@pytest.fixture
def sleep_calls(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Capture backoff sleeps instead of blocking the test."""
    calls: list[float] = []
    monkeypatch.setattr(httpx_module.time, "sleep", lambda seconds: calls.append(seconds))
    return calls


@pytest.fixture(autouse=True)
def no_retry_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clear the retry env variables so host settings never leak into the tests.

    Autouse: every test starts from the defaults. Tests that need an
    environment override still call ``monkeypatch.setenv`` after this fixture
    has run, so their own values take precedence.
    """
    monkeypatch.delenv(RETRYABLE_STATUS_CODES_ENV, raising=False)
    monkeypatch.delenv(RETRY_DELAYS_ENV, raising=False)


@pytest.mark.parametrize("status_code", RETRYABLE_CODES)
def test_httpx_fetcher_retries_transient_error_then_succeeds(
    httpx_mock: HTTPXMock,
    tmp_path: Path,
    sleep_calls: list[float],
    status_code: int,
) -> None:
    url = "https://example.com/flaky"
    httpx_mock.add_response(url=url, status_code=status_code)
    httpx_mock.add_response(url=url, text="<html>Recovered</html>")

    client = HttpxCrawlerRuntime("demo", tmp_path)
    result = client.fetcher(url)

    assert result == "<html>Recovered</html>"
    assert sleep_calls == [RETRY_BACKOFF[0]]
    assert len(httpx_mock.get_requests()) == 2
    assert client.sleep_duration_seconds == RETRY_BACKOFF[0]


def test_httpx_fetcher_retries_with_exponential_backoff_schedule(
    httpx_mock: HTTPXMock,
    tmp_path: Path,
    sleep_calls: list[float],
) -> None:
    url = "https://example.com/unavailable"
    httpx_mock.add_response(url=url, status_code=503)
    httpx_mock.add_response(url=url, status_code=503)
    httpx_mock.add_response(url=url, status_code=502)
    httpx_mock.add_response(url=url, status_code=504)
    httpx_mock.add_response(url=url, text="ok")

    client = HttpxCrawlerRuntime("demo", tmp_path)
    result = client.fetcher(url)

    assert result == "ok"
    # Attempt 1 -> 30s, attempt 2 -> 60s, attempt 3 -> 120s, attempt 4 -> 300s
    assert sleep_calls == [30.0, 60.0, 120.0, 300.0]
    assert client.sleep_duration_seconds == 510.0
    assert len(httpx_mock.get_requests()) == 5


def test_httpx_fetcher_fails_after_max_attempts(
    httpx_mock: HTTPXMock,
    tmp_path: Path,
    sleep_calls: list[float],
) -> None:
    url = "https://example.com/down"
    for _ in range(len(DEFAULT_RETRY_DELAYS_SECONDS) + 1):
        httpx_mock.add_response(url=url, status_code=503)

    client = HttpxCrawlerRuntime("demo", tmp_path)

    with pytest.raises(RuntimeError, match="HTTP error 503"):
        client.fetcher(url)

    # All backoff delays are consumed: the last attempt fails without sleeping.
    assert sleep_calls == list(DEFAULT_RETRY_DELAYS_SECONDS)
    assert client.max_attempts == 6
    assert len(httpx_mock.get_requests()) == 6


def test_httpx_fetcher_does_not_retry_non_retryable_status(
    httpx_mock: HTTPXMock,
    tmp_path: Path,
    sleep_calls: list[float],
) -> None:
    url = "https://example.com/not-found"
    httpx_mock.add_response(url=url, status_code=404)

    client = HttpxCrawlerRuntime("demo", tmp_path)

    with pytest.raises(RuntimeError, match="HTTP error 404"):
        client.fetcher(url)

    assert sleep_calls == []
    assert len(httpx_mock.get_requests()) == 1


def test_httpx_fetcher_does_not_retry_network_error(
    httpx_mock: HTTPXMock,
    tmp_path: Path,
    sleep_calls: list[float],
) -> None:
    url = "https://example.com/fail"
    httpx_mock.add_exception(httpx.ConnectError("connection refused"), url=url)

    client = HttpxCrawlerRuntime("demo", tmp_path)

    with pytest.raises(RuntimeError, match="Network error fetching URL"):
        client.fetcher(url)

    assert sleep_calls == []
    assert len(httpx_mock.get_requests()) == 1


def test_httpx_fetcher_retryable_codes_from_environment(
    httpx_mock: HTTPXMock,
    tmp_path: Path,
    sleep_calls: list[float],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(RETRYABLE_STATUS_CODES_ENV, "503, 429")
    url = "https://example.com/rate-limited"
    httpx_mock.add_response(url=url, status_code=429)
    httpx_mock.add_response(url=url, text="ok")

    client = HttpxCrawlerRuntime("demo", tmp_path)

    assert client.retryable_status_codes == (503, 429)
    assert client.fetcher(url) == "ok"
    assert sleep_calls == [30.0]


def test_httpx_fetcher_environment_override_disables_default_retries(
    httpx_mock: HTTPXMock,
    tmp_path: Path,
    sleep_calls: list[float],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(RETRYABLE_STATUS_CODES_ENV, "429")
    url = "https://example.com/unavailable"
    httpx_mock.add_response(url=url, status_code=503)

    client = HttpxCrawlerRuntime("demo", tmp_path)

    with pytest.raises(RuntimeError, match="HTTP error 503"):
        client.fetcher(url)

    assert sleep_calls == []
    assert len(httpx_mock.get_requests()) == 1


def test_httpx_fetcher_explicit_retry_config_overrides_environment(
    httpx_mock: HTTPXMock,
    tmp_path: Path,
    sleep_calls: list[float],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(RETRYABLE_STATUS_CODES_ENV, "429")
    url = "https://example.com/gateway"
    httpx_mock.add_response(url=url, status_code=502)
    httpx_mock.add_response(url=url, status_code=502)
    httpx_mock.add_response(url=url, text="ok")

    client = HttpxCrawlerRuntime(
        "demo",
        tmp_path,
        retryable_status_codes=(502,),
        retry_delays_seconds=(1.0, 2.0),
    )

    assert client.fetcher(url) == "ok"
    assert sleep_calls == [1.0, 2.0]
    assert client.max_attempts == 3


def test_httpx_fetcher_custom_backoff_raises_after_max_attempts(
    httpx_mock: HTTPXMock,
    tmp_path: Path,
    sleep_calls: list[float],
) -> None:
    url = "https://example.com/down"
    for _ in range(3):
        httpx_mock.add_response(url=url, status_code=504)

    client = HttpxCrawlerRuntime("demo", tmp_path, retry_delays_seconds=(0.5, 1.5))

    with pytest.raises(RuntimeError, match="HTTP error 504"):
        client.fetcher(url)

    assert sleep_calls == [0.5, 1.5]
    assert len(httpx_mock.get_requests()) == 3


# ---------------------------------------------------------------------------
# Shared validation of the retry configuration
# (constructor argument and environment variable use the same checks)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("codes", [(0,), (99,), (600,)])
def test_httpx_fetcher_rejects_invalid_status_codes_from_constructor(
    tmp_path: Path, codes: tuple[int, ...]
) -> None:
    with pytest.raises(ValueError, match="retryable_status_codes"):
        HttpxCrawlerRuntime("demo", tmp_path, retryable_status_codes=codes)


def test_httpx_fetcher_rejects_empty_status_codes_from_constructor(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="retryable_status_codes"):
        HttpxCrawlerRuntime("demo", tmp_path, retryable_status_codes=())


def test_validate_retryable_status_codes_keeps_order_and_duplicates() -> None:
    assert validate_retryable_status_codes([502, 429, 502]) == (502, 429, 502)


@pytest.mark.parametrize("codes", [(0,), (99,), (600,), ()])
def test_validate_retryable_status_codes_rejects_invalid_values(codes: tuple[int, ...]) -> None:
    with pytest.raises(ValueError, match=RETRYABLE_STATUS_CODES_ENV):
        validate_retryable_status_codes(codes)


def test_httpx_fetcher_rejects_negative_retry_delay_from_constructor(tmp_path: Path) -> None:
    """A negative delay would make time.sleep raise inside the retry loop."""
    with pytest.raises(ValueError, match="retry_delays_seconds"):
        HttpxCrawlerRuntime("demo", tmp_path, retry_delays_seconds=(-1.0,))


@pytest.mark.parametrize("invalid_delay", [float("inf"), float("nan")])
def test_httpx_fetcher_rejects_non_finite_retry_delay_from_constructor(
    tmp_path: Path, invalid_delay: float
) -> None:
    with pytest.raises(ValueError, match="retry_delays_seconds"):
        HttpxCrawlerRuntime("demo", tmp_path, retry_delays_seconds=(invalid_delay,))


def test_httpx_fetcher_rejects_empty_retry_delays_from_constructor(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="retry_delays_seconds"):
        HttpxCrawlerRuntime("demo", tmp_path, retry_delays_seconds=())


def test_validate_retry_delays_seconds_keeps_order_and_accepts_zero() -> None:
    assert validate_retry_delays_seconds((0, 1.5, 30.0)) == (0.0, 1.5, 30.0)


@pytest.mark.parametrize("delays", [(-1.0,), (1.0, -2.0), (float("inf"),), (float("nan"),), ()])
def test_validate_retry_delays_seconds_rejects_invalid_values(delays: tuple[float, ...]) -> None:
    with pytest.raises(ValueError, match=RETRY_DELAYS_ENV):
        validate_retry_delays_seconds(delays)


def test_validate_retry_delays_seconds_rejects_non_numeric_values() -> None:
    with pytest.raises(ValueError, match=RETRY_DELAYS_ENV):
        validate_retry_delays_seconds((None,))  # type: ignore[arg-type]


def test_httpx_fetcher_missing_retry_env_uses_default_codes(tmp_path: Path) -> None:
    client = HttpxCrawlerRuntime("demo", tmp_path)

    assert client.retryable_status_codes == DEFAULT_RETRYABLE_STATUS_CODES
    assert client.retry_delays_seconds == DEFAULT_RETRY_DELAYS_SECONDS
    assert client.max_attempts == len(DEFAULT_RETRY_DELAYS_SECONDS) + 1


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, (502, 503, 504)),
        ("", (502, 503, 504)),
        ("   ", (502, 503, 504)),
        ("503", (503,)),
        ("502,503,504", (502, 503, 504)),
        (" 502 , 429 ,, 500 ", (502, 429, 500)),
        ("503,503", (503,)),
    ],
)
def test_parse_retryable_status_codes(raw: str | None, expected: tuple[int, ...]) -> None:
    assert parse_retryable_status_codes(raw) == expected


@pytest.mark.parametrize("raw", ["abc", "502,foo", "99", "600", "-1", ","])
def test_parse_retryable_status_codes_rejects_invalid_values(raw: str) -> None:
    with pytest.raises(ValueError, match=RETRYABLE_STATUS_CODES_ENV):
        parse_retryable_status_codes(raw)


def test_httpx_fetcher_retry_delays_from_environment(
    httpx_mock: HTTPXMock,
    tmp_path: Path,
    sleep_calls: list[float],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(RETRY_DELAYS_ENV, "1,2.5,4")
    url = "https://example.com/unavailable"
    httpx_mock.add_response(url=url, status_code=503)
    httpx_mock.add_response(url=url, status_code=503)
    httpx_mock.add_response(url=url, status_code=503)
    httpx_mock.add_response(url=url, text="ok")

    client = HttpxCrawlerRuntime("demo", tmp_path)

    assert client.retry_delays_seconds == (1.0, 2.5, 4.0)
    assert client.max_attempts == 4
    assert client.fetcher(url) == "ok"
    assert sleep_calls == [1.0, 2.5, 4.0]


def test_httpx_fetcher_retry_delays_environment_raises_after_max_attempts(
    httpx_mock: HTTPXMock,
    tmp_path: Path,
    sleep_calls: list[float],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(RETRY_DELAYS_ENV, "1,2")
    url = "https://example.com/down"
    for _ in range(3):
        httpx_mock.add_response(url=url, status_code=502)

    client = HttpxCrawlerRuntime("demo", tmp_path)

    with pytest.raises(RuntimeError, match="HTTP error 502"):
        client.fetcher(url)

    assert sleep_calls == [1.0, 2.0]
    assert len(httpx_mock.get_requests()) == 3


def test_httpx_fetcher_explicit_retry_delays_override_environment(
    httpx_mock: HTTPXMock,
    tmp_path: Path,
    sleep_calls: list[float],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(RETRY_DELAYS_ENV, "100,200")
    url = "https://example.com/gateway"
    httpx_mock.add_response(url=url, status_code=504)
    httpx_mock.add_response(url=url, text="ok")

    client = HttpxCrawlerRuntime("demo", tmp_path, retry_delays_seconds=(0.01,))

    assert client.fetcher(url) == "ok"
    assert sleep_calls == [0.01]


def test_httpx_fetcher_single_retry_delay_env_means_two_attempts(
    httpx_mock: HTTPXMock,
    tmp_path: Path,
    sleep_calls: list[float],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(RETRY_DELAYS_ENV, "5")
    url = "https://example.com/down"
    httpx_mock.add_response(url=url, status_code=503)
    httpx_mock.add_response(url=url, status_code=503)

    client = HttpxCrawlerRuntime("demo", tmp_path)

    with pytest.raises(RuntimeError, match="HTTP error 503"):
        client.fetcher(url)

    assert client.max_attempts == 2
    assert sleep_calls == [5.0]
    assert len(httpx_mock.get_requests()) == 2


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, (30.0, 60.0, 120.0, 300.0, 3600.0)),
        ("", (30.0, 60.0, 120.0, 300.0, 3600.0)),
        ("   ", (30.0, 60.0, 120.0, 300.0, 3600.0)),
        ("10", (10.0,)),
        ("30,60,120", (30.0, 60.0, 120.0)),
        (" 1 , 2.5 ,, 0 ", (1.0, 2.5, 0.0)),
        ("0", (0.0,)),
    ],
)
def test_parse_retry_delays_seconds(raw: str | None, expected: tuple[float, ...]) -> None:
    assert parse_retry_delays_seconds(raw) == expected


@pytest.mark.parametrize("raw", ["abc", "30,foo", "-1", "1,-2", "nan", ","])
def test_parse_retry_delays_seconds_rejects_invalid_values(raw: str) -> None:
    with pytest.raises(ValueError, match=RETRY_DELAYS_ENV):
        parse_retry_delays_seconds(raw)


def test_httpx_fetcher_raises_on_external_redirect(httpx_mock: HTTPXMock, tmp_path: Path) -> None:
    url = "https://example.com/redirect"
    redirected_url = "https://external.com/page"
    httpx_mock.add_response(url=url, status_code=302, headers={"Location": redirected_url})
    httpx_mock.add_response(url=redirected_url, text="ok")

    client = HttpxCrawlerRuntime("demo", tmp_path, base_url="https://example.com")
    with pytest.raises(
        ExternalRedirectError,
        check=lambda e: e.requested_url == url and e.final_url == redirected_url,
    ):
        client.fetcher(url)


def _extract_url(args: tuple[object, ...], kwargs: dict[str, object]) -> str:
    if args:
        return str(args[0])
    return str(kwargs["url"])


def test_download_cache_miss_then_hit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def fake_get(*args, **kwargs):
        url = _extract_url(args, kwargs)
        calls.append(url)
        return httpx.Response(
            200,
            content=b"%PDF-1.7",
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr("ranking.core.crawler.httpx.httpx.get", fake_get)
    cache = HttpxCrawlerRuntime("demo", document_root=tmp_path)
    url = "https://example.com/race_info.pdf"

    cache.download(url)
    cache.download(url)
    assert calls == [url]


def test_downloader_returns_downloaded_document(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def fake_get(*args, **kwargs):
        url = _extract_url(args, kwargs)
        calls.append(url)
        return httpx.Response(
            200,
            content=b"%PDF-1.7",
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr("ranking.core.crawler.httpx.httpx.get", fake_get)
    cache = HttpxCrawlerRuntime("demo")
    url = "https://example.com/race_info.pdf"

    document = cache.downloader(url)

    assert calls == [url]
    assert document.url == url
    assert document.content == b"%PDF-1.7"
    assert document.content_length == len(b"%PDF-1.7")
    assert document.original_filename == "race_info.pdf"
    assert document.content_type == "application/octet-stream"


@pytest.mark.parametrize(
    ("url", "expected_suffix"),
    [
        ("https://example.com/race_info.pdf", ".pdf"),
        ("https://example.com/event_map.jpg?size=large", ".jpg"),
    ],
)
def test_download_preserves_file_extension(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    url: str,
    expected_suffix: str,
) -> None:
    def fake_get(*args, **kwargs):
        url = _extract_url(args, kwargs)
        return httpx.Response(
            200,
            content=b"content",
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr("ranking.core.crawler.httpx.httpx.get", fake_get)
    cache = HttpxCrawlerRuntime("demo", document_root=tmp_path)

    cache.download(url)
    document = cache.storage.get_document(url)

    assert document is not None and document.original_filename is not None
    assert document.original_filename.endswith(expected_suffix)


@pytest.mark.parametrize(
    ("url", "expected_suffix"),
    [
        ("https://example.com/race_info.pdf", ".pdf"),
        ("https://example.com/event_map.jpg?size=large", ".jpg"),
    ],
)
def test_downloader_preserves_file_extension(
    monkeypatch: pytest.MonkeyPatch,
    url: str,
    expected_suffix: str,
) -> None:
    def fake_get(*args, **kwargs):
        url = _extract_url(args, kwargs)
        return httpx.Response(
            200,
            content=b"content",
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr("ranking.core.crawler.httpx.httpx.get", fake_get)
    cache = HttpxCrawlerRuntime("demo")

    document = cache.downloader(url)

    assert document.original_filename is not None
    assert document.original_filename.endswith(expected_suffix)


def test_download_raises_runtime_error_on_network_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_get(*args, **kwargs):
        raise httpx.RequestError("boom", request=httpx.Request("GET", _extract_url(args, kwargs)))

    monkeypatch.setattr("ranking.core.crawler.httpx.httpx.get", fake_get)
    cache = HttpxCrawlerRuntime("demo", document_root=tmp_path)

    with pytest.raises(RuntimeError, match="Network error downloading URL"):
        cache.download("https://example.com/missing.pdf")


def test_downloader_raises_runtime_error_on_network_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_get(*args, **kwargs):
        raise httpx.RequestError("boom", request=httpx.Request("GET", _extract_url(args, kwargs)))

    monkeypatch.setattr("ranking.core.crawler.httpx.httpx.get", fake_get)
    cache = HttpxCrawlerRuntime("demo")

    with pytest.raises(RuntimeError, match="Network error downloading URL"):
        cache.downloader("https://example.com/missing.pdf")


# ---------------------------------------------------------------------------
# Integration test with custom storage provider
# ---------------------------------------------------------------------------


class StubStorageProvider(StorageProvider):
    """Minimal in-memory storage provider for testing HttpxClientWithCache."""

    def __init__(self, plugin_name: str) -> None:
        super().__init__(plugin_name)
        self._http_cache: dict[str, str] = {}
        self._extracted: dict[str, dict] = {}
        self._documents: dict[str, DownloadedDocument] = {}

    def save_http_cache(self, url: str, content: str) -> None:
        self._http_cache[url] = content

    def get_http_cache(self, url: str) -> str | None:
        return self._http_cache.get(url)

    def exists_http_cache(self, url: str) -> bool:
        return url in self._http_cache

    def save_http_snapshot(self, url: str, content: str, timestamp: str) -> None:
        pass  # Not needed for this test

    def list_http_snapshots(self, url: str) -> list[tuple[str, str]]:
        return []  # Not needed for this test

    def save_extracted(self, url: str, data: dict) -> None:
        self._extracted[url] = data

    def get_extracted(self, url: str) -> dict | None:
        return self._extracted.get(url)

    def save_document(self, document: DownloadedDocument) -> None:
        self._documents[document.url] = document

    def get_document(self, url: str) -> DownloadedDocument | None:
        return self._documents.get(url)

    def document_exists(self, url: str) -> bool:
        return url in self._documents

    def healthcheck(self) -> HealthCheckResult:
        return HealthCheckResult(success=True, backend="StubStorageProvider", details={}, checks={})


def test_httpx_cache_integration_with_storage_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify HttpxClientWithCache works end-to-end with any storage provider."""
    calls: list[str] = []

    def fake_get(*args, **kwargs):
        url = _extract_url(args, kwargs)
        calls.append(url)
        return httpx.Response(
            200, text="<html>cached content</html>", request=httpx.Request("GET", url)
        )

    monkeypatch.setattr("ranking.core.crawler.httpx.httpx.get", fake_get)

    storage = StubStorageProvider("myplugin")
    cache = HttpxCrawlerRuntime(plugin_name="myplugin", storage=storage)

    from ranking.core.crawler.runtime import CachePolicy

    url = "https://example.com/events"
    first = cache.fetch(url, CachePolicy.CACHE_IF_PRESENT)
    second = cache.fetch(url, CachePolicy.CACHE_IF_PRESENT)

    assert first == "<html>cached content</html>"
    assert second == "<html>cached content</html>"
    assert calls == [url]  # Only one network call
    assert storage.exists_http_cache(url)
