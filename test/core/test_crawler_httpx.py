from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from pytest_httpx import HTTPXMock

from ranking.core.crawler_httpx import HEADERS, HttpxCrawlerRuntime
from ranking.core.errors import ExternalRedirectError
from ranking.core.storage import DownloadedDocument, StorageProvider


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

    monkeypatch.setattr("ranking.core.crawler_httpx.httpx.get", fake_get)
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

    monkeypatch.setattr("ranking.core.crawler_httpx.httpx.get", fake_get)
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

    monkeypatch.setattr("ranking.core.crawler_httpx.httpx.get", fake_get)
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

    monkeypatch.setattr("ranking.core.crawler_httpx.httpx.get", fake_get)
    cache = HttpxCrawlerRuntime("demo")

    document = cache.downloader(url)

    assert document.original_filename is not None
    assert document.original_filename.endswith(expected_suffix)


def test_download_raises_runtime_error_on_network_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_get(*args, **kwargs):
        raise httpx.RequestError("boom", request=httpx.Request("GET", _extract_url(args, kwargs)))

    monkeypatch.setattr("ranking.core.crawler_httpx.httpx.get", fake_get)
    cache = HttpxCrawlerRuntime("demo", document_root=tmp_path)

    with pytest.raises(RuntimeError, match="Network error downloading URL"):
        cache.download("https://example.com/missing.pdf")


def test_downloader_raises_runtime_error_on_network_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_get(*args, **kwargs):
        raise httpx.RequestError("boom", request=httpx.Request("GET", _extract_url(args, kwargs)))

    monkeypatch.setattr("ranking.core.crawler_httpx.httpx.get", fake_get)
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


def test_httpx_cache_integration_with_storage_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify HttpxClientWithCache works end-to-end with any storage provider."""
    calls: list[str] = []

    def fake_get(*args, **kwargs):
        url = _extract_url(args, kwargs)
        calls.append(url)
        return httpx.Response(
            200, text="<html>cached content</html>", request=httpx.Request("GET", url)
        )

    monkeypatch.setattr("ranking.core.crawler_httpx.httpx.get", fake_get)

    storage = StubStorageProvider("myplugin")
    cache = HttpxCrawlerRuntime(plugin_name="myplugin", storage=storage)

    from ranking.core.crawler import CachePolicy

    url = "https://example.com/events"
    first = cache.fetch(url, CachePolicy.CACHE_IF_PRESENT)
    second = cache.fetch(url, CachePolicy.CACHE_IF_PRESENT)

    assert first == "<html>cached content</html>"
    assert second == "<html>cached content</html>"
    assert calls == [url]  # Only one network call
    assert storage.exists_http_cache(url)
