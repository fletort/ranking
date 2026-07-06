from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from pytest_httpx import HTTPXMock

from ranking.core.cache_httpx import HEADERS, HttpxClientWithCache
from ranking.core.errors import ExternalRedirectError


def test_httpx_fetcher_returns_html(httpx_mock: HTTPXMock, tmp_path: Path) -> None:
    url = "https://example.com/page"
    httpx_mock.add_response(url=url, text="<html>Hello</html>")

    client = HttpxClientWithCache("demo", tmp_path)
    result = client.fetcher(url)

    assert result == "<html>Hello</html>"


def test_httpx_fetcher_sends_custom_headers(httpx_mock: HTTPXMock, tmp_path: Path) -> None:
    url = "https://example.com/page"
    httpx_mock.add_response(url=url, text="ok")

    client = HttpxClientWithCache("demo", tmp_path)
    client.fetcher(url)

    requests = httpx_mock.get_requests()
    assert len(requests) == 1
    for header, value in HEADERS.items():
        assert requests[0].headers.get(header) == value


def test_httpx_fetcher_raises_on_http_error(httpx_mock: HTTPXMock, tmp_path: Path) -> None:
    url = "https://example.com/not-found"
    httpx_mock.add_response(url=url, status_code=404)

    client = HttpxClientWithCache("demo", tmp_path)
    with pytest.raises(RuntimeError, match="HTTP error 404"):
        client.fetcher(url)


def test_httpx_fetcher_raises_on_network_error(httpx_mock: HTTPXMock, tmp_path: Path) -> None:
    url = "https://example.com/fail"
    httpx_mock.add_exception(httpx.ConnectError("connection refused"), url=url)

    client = HttpxClientWithCache("demo", tmp_path)
    with pytest.raises(RuntimeError, match="Network error fetching URL"):
        client.fetcher(url)


def test_httpx_fetcher_raises_on_external_redirect(httpx_mock: HTTPXMock, tmp_path: Path) -> None:
    url = "https://example.com/redirect"
    redirected_url = "https://external.com/page"
    httpx_mock.add_response(url=url, status_code=302, headers={"Location": redirected_url})
    httpx_mock.add_response(url=redirected_url, text="ok")

    client = HttpxClientWithCache("demo", tmp_path, base_url="https://example.com")
    with pytest.raises(
        ExternalRedirectError,
        check=lambda e: e.requested_url == url and e.final_url == redirected_url,
    ):
        client.fetcher(url)
