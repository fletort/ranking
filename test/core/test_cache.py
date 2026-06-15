from datetime import datetime
from pathlib import Path

import pytest

from ranking.core.cache import CachePolicy, HTTPCacheV1


def test_derive_cache_key_ignores_query_parameter_order() -> None:
    url = "https://example.com/page?a=1&b=2"
    same_without_query_order = "https://example.com/page?b=2&a=1"
    with_different_query_value = "https://example.com/page?a=1&b=3"

    assert HTTPCacheV1.derive_cache_key(url) == HTTPCacheV1.derive_cache_key(
        same_without_query_order
    )
    assert HTTPCacheV1.derive_cache_key(url) != HTTPCacheV1.derive_cache_key(
        with_different_query_value
    )


def test_no_cache_policy_never_reads_or_writes_cache(tmp_path: Path) -> None:
    calls: list[str] = []

    def fetcher(url: str) -> str:
        calls.append(url)
        return "fresh-content"

    cache = HTTPCacheV1("demo", fetcher=fetcher, cache_root=tmp_path)
    content = cache.fetch("https://example.com/events", CachePolicy.NO_CACHE)

    assert content == "fresh-content"
    assert calls == ["https://example.com/events"]
    assert not (tmp_path / "demo" / "http").exists()


def test_cache_if_present_fetches_once_then_uses_cache(tmp_path: Path) -> None:
    calls: list[str] = []

    def fetcher(url: str) -> str:
        calls.append(url)
        return "cached-content"

    cache = HTTPCacheV1("demo", fetcher=fetcher, cache_root=tmp_path)
    url = "https://example.com/results/10km"

    first = cache.fetch(url, CachePolicy.CACHE_IF_PRESENT)
    second = cache.fetch(url, CachePolicy.CACHE_IF_PRESENT)

    assert first == "cached-content"
    assert second == "cached-content"
    assert calls == [url]
    assert cache.current_path(url).exists()


def test_refresh_and_cache_creates_snapshot_only_when_content_changes(tmp_path: Path) -> None:
    response_values = ["v1", "v1", "v2"]

    def fetcher(_: str) -> str:
        return response_values.pop(0)

    cache = HTTPCacheV1("demo", fetcher=fetcher, cache_root=tmp_path)
    url = "https://example.com/events/list"

    cache.fetch(url, CachePolicy.CACHE_IF_PRESENT)
    cache.fetch(url, CachePolicy.REFRESH_AND_CACHE)
    assert list(cache.snapshots_dir(url).glob("*.html")) == []

    updated = cache.fetch(url, CachePolicy.REFRESH_AND_CACHE)
    snapshot_files = list(cache.snapshots_dir(url).glob("*.html"))

    assert updated == "v2"
    assert cache.current_path(url).read_text(encoding="utf-8") == "v2"
    assert len(snapshot_files) == 1
    assert snapshot_files[0].suffix == ".html"
    datetime.strptime(snapshot_files[0].stem, "%Y-%m-%dT%H-%M-%S")
    assert snapshot_files[0].read_text(encoding="utf-8") == "v2"


def test_current_path_uses_sharding_and_slug(tmp_path: Path) -> None:
    cache = HTTPCacheV1("demo", fetcher=lambda _: "x", cache_root=tmp_path)
    url = "https://example.com/races/Trail de la Côte?city=Saint-Brieuc"

    current_path = cache.current_path(url)
    key = HTTPCacheV1.derive_cache_key(url)

    assert current_path.parent.name == key[:2]
    assert current_path.name.endswith(f"__{key[:8]}.html")
    assert "trail_de_la_c_te" in current_path.name


def test_fetch_propagates_network_errors(tmp_path: Path) -> None:
    def fetcher(_: str) -> str:
        raise RuntimeError("Network error")

    cache = HTTPCacheV1("demo", fetcher=fetcher, cache_root=tmp_path)

    with pytest.raises(RuntimeError, match="Network error"):
        cache.fetch("https://example.com/fail", CachePolicy.CACHE_IF_PRESENT)
