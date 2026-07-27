import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

import ranking.core.crawler.runtime as runtime_module
from ranking.core.crawler.runtime import CachePolicy, CrawlerRuntime
from ranking.core.storage.provider import DownloadedDocument


class EmptyFetcher(CrawlerRuntime):
    def __init__(self, cache_root, save_extracted=False) -> None:
        super().__init__("demo", cache_root, save_extracted=save_extracted)

    def fetcher(self, url: str) -> str:
        return ""


def test_no_cache_policy_never_reads_or_writes_cache(tmp_path: Path) -> None:
    calls: list[str] = []

    class DummyFetcher(CrawlerRuntime):
        def __init__(self) -> None:
            super().__init__("demo", cache_root=tmp_path)

        def fetcher(self, url: str) -> str:
            calls.append(url)
            return "fresh-content"

    cache = DummyFetcher()
    content = cache.fetch("https://example.com/events", CachePolicy.NO_CACHE)

    assert content == "fresh-content"
    assert calls == ["https://example.com/events"]
    assert not cache.storage.exists_http_cache("https://example.com/events")


def test_cache_if_present_fetches_once_then_uses_cache(tmp_path: Path) -> None:
    calls: list[str] = []

    class DummyFetcher(CrawlerRuntime):
        def __init__(self) -> None:
            super().__init__("demo", cache_root=tmp_path)

        def fetcher(self, url: str) -> str:
            calls.append(url)
            return "cached-content"

    cache = DummyFetcher()
    url = "https://example.com/results/10km"

    first = cache.fetch(url, CachePolicy.CACHE_IF_PRESENT)
    second = cache.fetch(url, CachePolicy.CACHE_IF_PRESENT)

    assert first == "cached-content"
    assert second == "cached-content"
    assert calls == [url]
    assert cache.storage.exists_http_cache(url)
    assert cache.cache_misses == 1
    assert cache.cache_hits == 1


def test_cache_if_present_cache_hit_does_not_sleep_or_fetch(tmp_path: Path, monkeypatch) -> None:
    sleep_calls: list[int | float] = []
    monkeypatch.setattr(runtime_module.time, "sleep", lambda seconds: sleep_calls.append(seconds))

    class DummyFetcher(CrawlerRuntime):
        def __init__(self) -> None:
            super().__init__(
                "demo", cache_root=tmp_path, network_sleep_seconds={"min": 1, "max": 3}
            )

        def fetcher(self, url: str) -> str:
            raise AssertionError("fetcher should not be called on cache hit")

    cache = DummyFetcher()
    url = "https://example.com/cached"
    cache.storage.save_http_cache(url, "cached-content")

    content = cache.fetch(url, CachePolicy.CACHE_IF_PRESENT)

    assert content == "cached-content"
    assert sleep_calls == []
    assert cache.sleep_duration_seconds == 0


def test_cache_if_present_cache_miss_sleeps_before_fetch(tmp_path: Path, monkeypatch) -> None:
    sleep_calls: list[int | float] = []
    monkeypatch.setattr(runtime_module.time, "sleep", lambda seconds: sleep_calls.append(seconds))

    class DummyFetcher(CrawlerRuntime):
        def __init__(self) -> None:
            super().__init__(
                "demo", cache_root=tmp_path, network_sleep_seconds={"min": 1, "max": 3}
            )

        def fetcher(self, url: str) -> str:
            return "fresh-content"

    cache = DummyFetcher()
    url = "https://example.com/miss"

    content = cache.fetch(url, CachePolicy.CACHE_IF_PRESENT)

    assert content == "fresh-content"
    assert sleep_calls[0] >= 1 and sleep_calls[0] <= 3
    assert cache.sleep_duration_seconds == sleep_calls[0]


def test_refresh_and_cache_creates_snapshot_only_when_content_changes(tmp_path: Path) -> None:
    response_values = ["v1", "v1", "v2", "v3"]

    class DummyFetcher(CrawlerRuntime):
        def __init__(self) -> None:
            super().__init__("demo", cache_root=tmp_path)

        def fetcher(self, url: str) -> str:
            return response_values.pop(0)

    cache = DummyFetcher()
    url = "https://example.com/events/list"

    first = cache.fetch(url, CachePolicy.REFRESH_AND_CACHE)
    # Check that the first fetch created the current cache
    assert first == "v1"
    assert cache.storage.get_http_cache(url) == "v1"
    assert len(cache.storage.list_http_snapshots(url)) == 0

    same = cache.fetch(url, CachePolicy.REFRESH_AND_CACHE)
    # Check that current cache is still the same and no snapshot was created
    assert same == "v1"
    assert cache.storage.get_http_cache(url) == "v1"
    assert len(cache.storage.list_http_snapshots(url)) == 0

    time.sleep(0.01)  # Ensure the timestamp changes for the next snapshot
    updated = cache.fetch(url, CachePolicy.REFRESH_AND_CACHE)
    # Check that the current cache was updated and a snapshot was created
    assert updated == "v2"
    assert cache.storage.get_http_cache(url) == "v2"
    snapshots = cache.storage.list_http_snapshots(url)
    assert len(snapshots) == 1
    ts1, content1 = snapshots[0]
    assert content1 == "v1"
    datetime.strptime(ts1, "%Y-%m-%dT%H-%M-%S-%f")

    time.sleep(0.01)  # Ensure the timestamp changes for the next snapshot
    updated = cache.fetch(url, CachePolicy.REFRESH_AND_CACHE)
    # Check that the current cache was updated and a new snapshot was created
    assert updated == "v3"
    assert cache.storage.get_http_cache(url) == "v3"
    snapshots = cache.storage.list_http_snapshots(url)
    assert len(snapshots) == 2
    ts2, content2 = snapshots[1]
    assert content2 == "v2"
    datetime.strptime(ts2, "%Y-%m-%dT%H-%M-%S-%f")
    # Second snapshot must be later than the first
    assert ts2 > ts1
    # First snapshot is still present and unchanged
    assert snapshots[0] == (ts1, content1)


def test_fetch_propagates_network_errors(tmp_path: Path) -> None:

    class DummyFetcher(CrawlerRuntime):
        def __init__(self) -> None:
            super().__init__("demo", cache_root=tmp_path)

        def fetcher(self, url: str) -> str:
            raise RuntimeError("Network error")

    cache = DummyFetcher()

    with pytest.raises(RuntimeError, match="Network error"):
        cache.fetch("https://example.com/fail", CachePolicy.CACHE_IF_PRESENT)


def test_save_extracted_json_disabled_by_default(tmp_path: Path) -> None:
    cache = EmptyFetcher(cache_root=tmp_path)
    url = "https://example.com/events"

    cache.save_extracted_json(url, {"key": "value"})

    assert cache.storage.get_extracted(url) is None


def test_save_extracted_json_persists_when_enabled(tmp_path: Path) -> None:
    cache = EmptyFetcher(cache_root=tmp_path, save_extracted=True)
    url = "https://example.com/events"
    data = [{"name": "Race A", "distance": 10}]

    cache.save_extracted_json(url, data)

    saved = cache.storage.get_extracted(url)
    assert saved == data


def test_save_extracted_json_uses_same_key_as_http_cache(tmp_path: Path) -> None:
    cache = EmptyFetcher(cache_root=tmp_path, save_extracted=True)
    url = "https://example.com/page?b=2&a=1"
    url_reordered = "https://example.com/page?a=1&b=2"

    cache.save_extracted_json(url, {"x": 1})

    assert cache.storage.get_extracted(url_reordered) is not None


def test_save_extracted_json_is_indented_for_readability(tmp_path: Path) -> None:
    from ranking.core.storage import LocalStorageProvider

    cache = EmptyFetcher(cache_root=tmp_path, save_extracted=True)
    url = "https://example.com/detail"
    data = {"name": "Alice", "time": "01:23:45"}

    cache.save_extracted_json(url, data)

    assert isinstance(cache.storage, LocalStorageProvider)
    raw = cache.storage._extracted_path(url).read_text(encoding="utf-8")
    assert "\n" in raw
    assert "  " in raw


def test_download_uses_subclass_downloader_and_caches_document(tmp_path: Path) -> None:
    calls: list[str] = []

    class DummyDownloader(CrawlerRuntime):
        def __init__(self) -> None:
            super().__init__("demo", cache_root=tmp_path, document_root=tmp_path)

        def fetcher(self, url: str) -> str:
            return ""

        def downloader(self, url: str) -> DownloadedDocument:
            calls.append(url)
            return DownloadedDocument(
                url=url,
                content=b"pdf-content",
                original_filename="race.pdf",
                content_type="application/pdf",
                content_length=11,
                downloaded_at=datetime.now(timezone.utc),
            )

    cache = DummyDownloader()
    url = "https://example.com/race.pdf"

    cache.download(url)
    cache.download(url)

    saved = cache.storage.get_document(url)
    assert calls == [url]
    assert saved is not None
    assert saved.content == b"pdf-content"
    assert saved.original_filename == "race.pdf"
