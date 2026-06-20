import os
import time
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
    response_values = ["v1", "v1", "v2", "v3"]

    def fetcher(_: str) -> str:
        return response_values.pop(0)

    cache = HTTPCacheV1("demo", fetcher=fetcher, cache_root=tmp_path)
    url = "https://example.com/events/list"

    first = cache.fetch(url, CachePolicy.REFRESH_AND_CACHE)
    # Check that the first fetch created the current cache
    assert first == "v1"
    assert cache.current_path(url).read_text(encoding="utf-8") == "v1"
    snapshot_files = list(cache.snapshots_dir(url).glob("*.html"))
    assert len(snapshot_files) == 0
    first_current_stat = os.stat(cache.current_path(url))

    same = cache.fetch(url, CachePolicy.REFRESH_AND_CACHE)
    # Check that current cache is still the same and no snapshot was created
    assert same == "v1"
    assert os.stat(cache.current_path(url)) == first_current_stat
    assert cache.current_path(url).read_text(encoding="utf-8") == "v1"
    snapshot_files = list(cache.snapshots_dir(url).glob("*.html"))
    assert len(snapshot_files) == 0

    time.sleep(0.01)  # Ensure the timestamp changes for the next snapshot
    updated = cache.fetch(url, CachePolicy.REFRESH_AND_CACHE)
    # Check that the current cache was updated and a snapshot was created
    assert updated == "v2"
    assert cache.current_path(url).read_text(encoding="utf-8") == "v2"
    snapshot_files = list(cache.snapshots_dir(url).glob("*.html"))
    assert len(snapshot_files) == 1
    first_snapshot_file = snapshot_files[0]
    first_snapshot_file_stat = os.stat(first_snapshot_file)
    assert first_snapshot_file.read_text(encoding="utf-8") == "v1"
    datetime.strptime(first_snapshot_file.stem, "%Y-%m-%dT%H-%M-%S-%f")

    time.sleep(0.01)  # Ensure the timestamp changes for the next snapshot
    updated = cache.fetch(url, CachePolicy.REFRESH_AND_CACHE)
    # Check that the current cache was updated and a new snapshot was created
    assert updated == "v3"
    assert cache.current_path(url).read_text(encoding="utf-8") == "v3"
    snapshot_files = list(cache.snapshots_dir(url).glob("*.html"))
    assert len(snapshot_files) == 2
    assert first_snapshot_file in snapshot_files
    for file in snapshot_files:
        if file == first_snapshot_file:
            assert os.path.samefile(file, first_snapshot_file)
            assert os.stat(file) == first_snapshot_file_stat
            assert file.read_text(encoding="utf-8") == "v1"
        else:
            datetime.strptime(file.stem, "%Y-%m-%dT%H-%M-%S-%f")
            assert os.path.getmtime(file) > os.path.getmtime(first_snapshot_file)
            assert file.read_text(encoding="utf-8") == "v2"


def test_fetch_propagates_network_errors(tmp_path: Path) -> None:
    def fetcher(_: str) -> str:
        raise RuntimeError("Network error")

    cache = HTTPCacheV1("demo", fetcher=fetcher, cache_root=tmp_path)

    with pytest.raises(RuntimeError, match="Network error"):
        cache.fetch("https://example.com/fail", CachePolicy.CACHE_IF_PRESENT)


def test_save_extracted_json_disabled_by_default(tmp_path: Path) -> None:
    cache = HTTPCacheV1("demo", fetcher=lambda url: "", cache_root=tmp_path)
    url = "https://example.com/events"

    cache.save_extracted_json(url, {"key": "value"})

    assert not cache.extracted_json_path(url).exists()


def test_save_extracted_json_persists_when_enabled(tmp_path: Path) -> None:
    cache = HTTPCacheV1("demo", fetcher=lambda url: "", cache_root=tmp_path, save_extracted=True)
    url = "https://example.com/events"
    data = [{"name": "Race A", "distance": 10}]

    cache.save_extracted_json(url, data)

    path = cache.extracted_json_path(url)
    assert path.exists()
    import json

    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved == data


def test_save_extracted_json_uses_same_key_as_http_cache(tmp_path: Path) -> None:
    cache = HTTPCacheV1("demo", fetcher=lambda url: "", cache_root=tmp_path, save_extracted=True)
    url = "https://example.com/page?b=2&a=1"
    url_reordered = "https://example.com/page?a=1&b=2"

    cache.save_extracted_json(url, {"x": 1})
    path_reordered = cache.extracted_json_path(url_reordered)

    assert path_reordered.exists()


def test_save_extracted_json_sharding_matches_http_cache(tmp_path: Path) -> None:
    cache = HTTPCacheV1("demo", fetcher=lambda url: "", cache_root=tmp_path, save_extracted=True)
    url = "https://example.com/results"

    cache.save_extracted_json(url, {"results": []})

    key = HTTPCacheV1.derive_cache_key(url)
    shard = key[:2]
    expected_path = tmp_path / "demo" / "extracted" / shard / f"{key}.json"
    assert expected_path.exists()


def test_save_extracted_json_is_indented_for_readability(tmp_path: Path) -> None:
    cache = HTTPCacheV1("demo", fetcher=lambda url: "", cache_root=tmp_path, save_extracted=True)
    url = "https://example.com/detail"
    data = {"name": "Alice", "time": "01:23:45"}

    cache.save_extracted_json(url, data)

    raw = cache.extracted_json_path(url).read_text(encoding="utf-8")
    assert "\n" in raw
    assert "  " in raw
