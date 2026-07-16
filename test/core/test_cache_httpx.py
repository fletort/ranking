from pathlib import Path

import httpx
import pytest

from ranking.core.cache import HttpClientWithCache
from ranking.core.cache_httpx import HttpxClientWithCache


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

    monkeypatch.setattr("ranking.core.cache_httpx.httpx.get", fake_get)
    cache = HttpxClientWithCache("demo", document_root=tmp_path)
    url = "https://example.com/race_info.pdf"

    first = cache.download(url)
    second = cache.download(url)

    assert first == second
    assert first.exists()
    assert first.read_bytes() == b"%PDF-1.7"
    assert calls == [url]


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

    monkeypatch.setattr("ranking.core.cache_httpx.httpx.get", fake_get)
    cache = HttpxClientWithCache("demo", document_root=tmp_path)

    path = cache.download(url)

    assert path.suffix == expected_suffix


def test_download_uses_document_sharding_and_cache_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_get(*args, **kwargs):
        url = _extract_url(args, kwargs)
        return httpx.Response(
            200,
            content=b"binary",
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr("ranking.core.cache_httpx.httpx.get", fake_get)
    cache = HttpxClientWithCache("breizhchrono", document_root=tmp_path)
    url = "https://example.com/files/race_info.pdf"
    key = HttpClientWithCache.derive_cache_key(url)
    shard = key[:2]

    path = cache.download(url)

    assert path.parent == tmp_path / "breizhchrono" / shard / key
    assert path.exists()


def test_download_raises_runtime_error_on_network_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_get(*args, **kwargs):
        raise httpx.RequestError("boom", request=httpx.Request("GET", _extract_url(args, kwargs)))

    monkeypatch.setattr("ranking.core.cache_httpx.httpx.get", fake_get)
    cache = HttpxClientWithCache("demo", document_root=tmp_path)

    with pytest.raises(RuntimeError, match="Network error downloading URL"):
        cache.download("https://example.com/missing.pdf")
