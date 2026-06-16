from __future__ import annotations

import httpx
import pytest
from pytest_httpx import HTTPXMock

from ranking.core.httpx_fetcher import HEADERS, httpx_fetcher


def test_httpx_fetcher_returns_html(httpx_mock: HTTPXMock) -> None:
    url = "https://example.com/page"
    httpx_mock.add_response(url=url, text="<html>Hello</html>")

    result = httpx_fetcher(url)

    assert result == "<html>Hello</html>"


def test_httpx_fetcher_sends_custom_headers(httpx_mock: HTTPXMock) -> None:
    url = "https://example.com/page"
    httpx_mock.add_response(url=url, text="ok")

    httpx_fetcher(url)

    requests = httpx_mock.get_requests()
    assert len(requests) == 1
    for header, value in HEADERS.items():
        assert requests[0].headers.get(header) == value


def test_httpx_fetcher_raises_on_http_error(httpx_mock: HTTPXMock) -> None:
    url = "https://example.com/not-found"
    httpx_mock.add_response(url=url, status_code=404)

    with pytest.raises(RuntimeError, match="HTTP error 404"):
        httpx_fetcher(url)


def test_httpx_fetcher_raises_on_network_error(httpx_mock: HTTPXMock) -> None:
    url = "https://example.com/fail"
    httpx_mock.add_exception(httpx.ConnectError("connection refused"), url=url)

    with pytest.raises(RuntimeError, match="Network error fetching URL"):
        httpx_fetcher(url)
