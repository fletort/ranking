import io
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

import ranking.core.crawler.runtime as runtime_module
from ranking.core.crawler.runtime import (
    CachePolicy,
    CrawlerRuntime,
    FetchedResource,
    default_is_temporary_unavailable_page,
)
from ranking.core.storage.local import LocalStorageProvider
from ranking.core.storage.provider import DownloadedDocument, StorageProvider
from ranking.core.storage.race_archive import ArchiveArea
from ranking.core.storage.race_archive import race_session as storage_race_session


class PlainFetcher(CrawlerRuntime):
    """Minimal concrete runtime with the default (no-op) hooks."""

    def fetcher(self, url: str) -> FetchedResource:
        return FetchedResource(url, url, "")


class EmptyFetcher(CrawlerRuntime):
    def __init__(self, cache_root, save_extracted=False) -> None:
        super().__init__("demo", cache_root, save_extracted=save_extracted)

    def fetcher(self, url: str) -> FetchedResource:
        return FetchedResource(url, url, "")


def test_no_cache_policy_never_reads_or_writes_cache(tmp_path: Path) -> None:
    calls: list[str] = []

    class DummyFetcher(CrawlerRuntime):
        def __init__(self) -> None:
            super().__init__("demo", cache_root=tmp_path)

        def fetcher(self, url: str) -> FetchedResource:
            calls.append(url)
            return FetchedResource(url, url, "fresh-content")

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

        def fetcher(self, url: str) -> FetchedResource:
            calls.append(url)
            return FetchedResource(url, url, "cached-content")

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

        def fetcher(self, url: str) -> FetchedResource:
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

        def fetcher(self, url: str) -> FetchedResource:
            return FetchedResource(url, url, "fresh-content")

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

        def fetcher(self, url: str) -> FetchedResource:
            return FetchedResource(url, url, response_values.pop(0))

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


def test_default_is_temporary_unavailable_page_returns_false() -> None:
    assert default_is_temporary_unavailable_page("https://example.com", "<html>ok</html>") is False


def test_crawler_runtime_default_temporary_unavailable_hook_returns_false() -> None:
    cache = PlainFetcher("demo")

    assert cache.is_temporary_unavailable_page("https://example.com", "<html>ok</html>") is False


def test_crawler_runtime_uses_custom_temporary_unavailable_hook() -> None:
    calls: list[tuple[str, str]] = []

    def hook(url: str, content: str) -> bool:
        calls.append((url, content))
        return True

    cache = PlainFetcher("demo", is_temporary_unavailable_page=hook)

    assert cache.is_temporary_unavailable_page("https://example.com", "<html>ok</html>") is True
    assert calls == [("https://example.com", "<html>ok</html>")]


def test_cache_if_present_refetches_flagged_cached_content(tmp_path: Path) -> None:
    calls: list[str] = []

    class DummyFetcher(CrawlerRuntime):
        def __init__(self) -> None:
            super().__init__(
                "demo",
                cache_root=tmp_path,
                network_sleep_seconds={"min": 0, "max": 0},
                is_temporary_unavailable_page=lambda url, content: "maintenance" in content,
            )

        def fetcher(self, url: str) -> FetchedResource:
            calls.append(url)
            return FetchedResource(url, url, "fresh-content")

    cache = DummyFetcher()
    url = "https://example.com/events"
    cache.storage.save_http_cache(url, "maintenance-page")

    content = cache.fetch(url, CachePolicy.CACHE_IF_PRESENT)

    assert content == "fresh-content"
    assert calls == [url]
    assert cache.storage.get_http_cache(url) == "fresh-content"
    assert cache.cache_hits == 0
    assert cache.cache_misses == 1


def test_cache_if_present_still_hits_for_valid_cached_content(tmp_path: Path) -> None:
    class DummyFetcher(CrawlerRuntime):
        def __init__(self) -> None:
            super().__init__(
                "demo",
                cache_root=tmp_path,
                network_sleep_seconds={"min": 0, "max": 0},
                is_temporary_unavailable_page=lambda url, content: "maintenance" in content,
            )

        def fetcher(self, url: str) -> FetchedResource:
            raise AssertionError("fetcher should not be called for a valid cache hit")

    cache = DummyFetcher()
    url = "https://example.com/events"
    cache.storage.save_http_cache(url, "valid-content")

    content = cache.fetch(url, CachePolicy.CACHE_IF_PRESENT)

    assert content == "valid-content"
    assert cache.cache_hits == 1
    assert cache.cache_misses == 0


def test_refresh_and_cache_does_not_snapshot_flagged_cached_content(tmp_path: Path) -> None:
    class DummyFetcher(CrawlerRuntime):
        def __init__(self) -> None:
            super().__init__(
                "demo",
                cache_root=tmp_path,
                network_sleep_seconds={"min": 0, "max": 0},
                is_temporary_unavailable_page=lambda url, content: "maintenance" in content,
            )

        def fetcher(self, url: str) -> FetchedResource:
            return FetchedResource(url, url, "fresh-content")

    cache = DummyFetcher()
    url = "https://example.com/events"
    cache.storage.save_http_cache(url, "maintenance-page")

    content = cache.fetch(url, CachePolicy.REFRESH_AND_CACHE)

    assert content == "fresh-content"
    assert cache.storage.get_http_cache(url) == "fresh-content"
    assert cache.storage.list_http_snapshots(url) == []


def test_fetch_propagates_network_errors(tmp_path: Path) -> None:
    class DummyFetcher(CrawlerRuntime):
        def __init__(self) -> None:
            super().__init__("demo", cache_root=tmp_path)

        def fetcher(self, url: str) -> FetchedResource:
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

        def fetcher(self, url: str) -> FetchedResource:
            return FetchedResource(url, url, "")

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


@pytest.mark.parametrize("cache_policy", list(CachePolicy))
def test_base_runtime_rejects_flagged_fresh_content_without_writing(
    tmp_path: Path, cache_policy: CachePolicy
) -> None:
    """Safety net: a flagged fresh response is rejected before any cache or snapshot write.

    Retrying belongs to the ``fetcher`` implementation (see ``HttpxCrawlerRuntime``); this guard
    only ensures a custom ``fetcher`` returning a temporary unavailable page cannot persist it.
    """

    class DummyFetcher(CrawlerRuntime):
        def __init__(self) -> None:
            super().__init__(
                "demo",
                cache_root=tmp_path,
                network_sleep_seconds={"min": 0, "max": 0},
                is_temporary_unavailable_page=lambda url, content: "maintenance" in content,
            )

        def fetcher(self, url: str) -> FetchedResource:
            return FetchedResource(url, url, "maintenance-page")

    cache = DummyFetcher()
    url = "https://example.com/events"

    with pytest.raises(RuntimeError, match="Temporary unavailable page"):
        cache.fetch(url, cache_policy)

    assert not cache.storage.exists_http_cache(url)
    assert cache.storage.list_http_snapshots(url) == []


# ---------------------------------------------------------------------------
# HTTP redirects (canonical identity + redirect pointers)
# ---------------------------------------------------------------------------


class RedirectFetcher(CrawlerRuntime):
    """Runtime whose fetcher returns a configurable final URL per requested URL."""

    def __init__(
        self, cache_root: Path, redirects: dict[str, str] | None = None, content: str = "body"
    ) -> None:
        super().__init__("demo", cache_root=cache_root, network_sleep_seconds={"min": 0, "max": 0})
        self.redirects = redirects or {}
        self.content = content
        self.calls: list[str] = []

    def fetcher(self, url: str) -> FetchedResource:
        self.calls.append(url)
        return FetchedResource(url, self.redirects.get(url, url), self.content)


def test_cache_if_present_redirect_stores_content_under_final_url(tmp_path: Path) -> None:
    a = "https://example.com/a"
    b = "https://example.com/b"
    cache = RedirectFetcher(tmp_path, {a: b}, content="body-b")

    content = cache.fetch(a, CachePolicy.CACHE_IF_PRESENT)

    assert content == "body-b"
    assert cache.storage.get_http_cache(b) == "body-b"
    assert not cache.storage.exists_http_cache(a)
    assert cache.storage.get_redirect(a) == b


def test_cache_if_present_redirect_hit_does_not_fetch_again(tmp_path: Path) -> None:
    a = "https://example.com/a"
    b = "https://example.com/b"
    cache = RedirectFetcher(tmp_path, {a: b}, content="body-b")

    first = cache.fetch(a, CachePolicy.CACHE_IF_PRESENT)
    second = cache.fetch(a, CachePolicy.CACHE_IF_PRESENT)

    assert first == second == "body-b"
    assert cache.calls == [a]
    assert cache.cache_hits == 1
    assert cache.cache_misses == 1


def test_no_cache_redirect_does_not_persist_pointer(tmp_path: Path) -> None:
    a = "https://example.com/a"
    b = "https://example.com/b"
    cache = RedirectFetcher(tmp_path, {a: b}, content="body-b")

    content = cache.fetch(a, CachePolicy.NO_CACHE)

    assert content == "body-b"
    assert cache.storage.get_redirect(a) is None
    assert not cache.storage.exists_http_cache(b)


def test_redirect_chain_resolves_transitively_without_network(tmp_path: Path) -> None:
    a = "https://example.com/a"
    b = "https://example.com/b"
    c = "https://example.com/c"
    cache = RedirectFetcher(tmp_path, content="body-c")
    # Stale chain A -> B -> C with C's body cached (B never owned a body).
    cache.storage.save_redirect(a, b)
    cache.storage.save_redirect(b, c)
    cache.storage.save_http_cache(c, "body-c")

    content = cache.fetch(a, CachePolicy.CACHE_IF_PRESENT)

    assert content == "body-c"
    assert cache.calls == []
    assert cache.cache_hits == 1


def test_resolve_redirect_returns_self_without_pointer(tmp_path: Path) -> None:
    cache = RedirectFetcher(tmp_path)
    url = "https://example.com/x"

    assert cache._resolve_redirect(url) == url


def test_resolve_redirect_detects_cycle(tmp_path: Path) -> None:
    a = "https://example.com/a"
    b = "https://example.com/b"
    cache = RedirectFetcher(tmp_path)
    cache.storage.save_redirect(a, b)
    cache.storage.save_redirect(b, a)

    assert cache._resolve_redirect(a) is None


def test_resolve_redirect_respects_hop_limit(tmp_path: Path) -> None:
    cache = RedirectFetcher(tmp_path)
    cache.max_redirect_hops = 2
    urls = [f"https://example.com/{index}" for index in range(5)]
    for source, target in zip(urls, urls[1:]):
        cache.storage.save_redirect(source, target)

    assert cache._resolve_redirect(urls[0]) is None


def test_cache_if_present_invalid_chain_breaks_cycle_and_refetches(tmp_path: Path) -> None:
    a = "https://example.com/a"
    b = "https://example.com/b"
    cache = RedirectFetcher(tmp_path, {a: b}, content="fresh")
    cache.storage.save_redirect(a, b)
    cache.storage.save_redirect(b, a)  # cycle
    cache.storage.save_http_cache(a, "legacy-body")  # must not be used (pointer precedence)

    content = cache.fetch(a, CachePolicy.CACHE_IF_PRESENT)

    assert content == "fresh"
    assert cache.calls == [a]
    assert cache.storage.get_http_cache(b) == "fresh"
    assert cache.storage.get_redirect(a) == b
    assert cache.storage.get_redirect(b) is None


def test_refresh_and_cache_redirect_snapshots_under_final_url(tmp_path: Path) -> None:
    a = "https://example.com/a"
    b = "https://example.com/b"
    responses = iter(["v1", "v2"])

    class Fetcher(CrawlerRuntime):
        def __init__(self) -> None:
            super().__init__(
                "demo", cache_root=tmp_path, network_sleep_seconds={"min": 0, "max": 0}
            )

        def fetcher(self, url: str) -> FetchedResource:
            return FetchedResource(url, b, next(responses))

    cache = Fetcher()

    assert cache.fetch(a, CachePolicy.REFRESH_AND_CACHE) == "v1"
    assert cache.storage.get_http_cache(b) == "v1"
    assert cache.storage.get_redirect(a) == b

    assert cache.fetch(a, CachePolicy.REFRESH_AND_CACHE) == "v2"
    assert cache.storage.get_http_cache(b) == "v2"
    assert not cache.storage.exists_http_cache(a)
    snapshots = cache.storage.list_http_snapshots(b)
    assert [value for _, value in snapshots] == ["v1"]


def test_refresh_removes_stale_pointer_at_final_url(tmp_path: Path) -> None:
    a = "https://example.com/a"
    b = "https://example.com/b"
    c = "https://example.com/c"
    cache = RedirectFetcher(tmp_path, {a: b}, content="body-b")
    # B previously redirected to C: that pointer is now stale and must be broken.
    cache.storage.save_redirect(b, c)

    cache.fetch(a, CachePolicy.REFRESH_AND_CACHE)

    assert cache.storage.get_redirect(b) is None
    assert cache.storage.get_redirect(a) == b


def test_redirect_with_same_resource_id_keeps_body_without_pointer(tmp_path: Path) -> None:
    a = "https://example.com/page?b=2&a=1"
    b = "https://example.com/page?a=1&b=2"  # same Resource ID as A
    cache = RedirectFetcher(tmp_path, {a: b}, content="body")

    content = cache.fetch(a, CachePolicy.CACHE_IF_PRESENT)

    assert content == "body"
    assert cache.storage.get_http_cache(a) == "body"
    assert cache.storage.get_redirect(a) is None


def test_refresh_removes_pointer_when_url_stops_redirecting(tmp_path: Path) -> None:
    a = "https://example.com/a"
    b = "https://example.com/b"

    class Fetcher(CrawlerRuntime):
        def __init__(self) -> None:
            super().__init__(
                "demo", cache_root=tmp_path, network_sleep_seconds={"min": 0, "max": 0}
            )
            self.redirect = True

        def fetcher(self, url: str) -> FetchedResource:
            return FetchedResource(url, b if self.redirect else url, "content")

    cache = Fetcher()
    cache.fetch(a, CachePolicy.REFRESH_AND_CACHE)
    assert cache.storage.get_redirect(a) == b

    cache.redirect = False
    cache.fetch(a, CachePolicy.REFRESH_AND_CACHE)

    assert cache.storage.get_redirect(a) is None
    assert cache.storage.get_http_cache(a) == "content"


# ---------------------------------------------------------------------------
# Race sessions (runtime provider swap + per-race archives)
# ---------------------------------------------------------------------------


class SessionStorageProvider(LocalStorageProvider):
    """Base provider exposing race archive support, backing the runtime swap tests."""

    def __init__(self, root: Path) -> None:
        super().__init__("demo", cache_root=root / "cache", document_root=root / "documents")
        self.session_urls: list[str] = []
        self.uploaded: dict[ArchiveArea, bytes] = {}

    def download_area_archive(self, race_url: str, area: ArchiveArea, target: Path) -> bool:
        return False

    def upload_area_archive(self, race_url: str, area: ArchiveArea, source: Path) -> None:
        self.uploaded[area] = source.read_bytes()

    def race_session(self, race_url: str):
        self.session_urls.append(race_url)
        return storage_race_session(self, race_url)


class StorageFetcher(CrawlerRuntime):
    """Runtime using an injected storage provider, with configurable redirects."""

    def __init__(
        self,
        storage: StorageProvider,
        redirects: dict[str, str] | None = None,
        content: str = "body",
    ) -> None:
        super().__init__("demo", network_sleep_seconds={"min": 0, "max": 0}, storage=storage)
        self.redirects = redirects or {}
        self.content = content

    def fetcher(self, url: str) -> FetchedResource:
        return FetchedResource(url, self.redirects.get(url, url), self.content)


def _zip_names(data: bytes) -> set[str]:
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        return set(zf.namelist())


def test_race_session_swaps_and_restores_storage(tmp_path: Path) -> None:
    base = SessionStorageProvider(tmp_path)
    cache = StorageFetcher(base)

    with cache.race_session("https://example.com/race/1") as scoped:
        assert cache.storage is scoped
        assert cache.storage is not base

    assert cache.storage is base


def test_race_session_restores_storage_when_body_raises(tmp_path: Path) -> None:
    base = SessionStorageProvider(tmp_path)
    cache = StorageFetcher(base)

    with pytest.raises(RuntimeError, match="boom"):
        with cache.race_session("https://example.com/race/1"):
            raise RuntimeError("boom")

    assert cache.storage is base


def test_race_session_writes_go_to_scoped_provider(tmp_path: Path) -> None:
    a = "https://example.com/a"
    b = "https://example.com/b"
    race_url = "https://example.com/race/1"
    base = SessionStorageProvider(tmp_path)
    cache = StorageFetcher(base, {a: b}, content="body-b")

    with cache.race_session(race_url):
        cache.fetch(a, CachePolicy.CACHE_IF_PRESENT)

    assert cache.storage is base
    assert base.session_urls == [race_url]
    # Nothing leaked to the base provider: writes were buffered by the scoped provider.
    assert base.get_http_cache(b) is None
    assert base.get_redirect(a) is None
    # On close, buffered artifacts were archived (HTTP archive bundles bodies + pointers).
    body_rid = base.compute_resource_id(b)
    redirect_rid = base.compute_resource_id(a)
    http_names = _zip_names(base.uploaded[ArchiveArea.HTTP])
    assert f"http/current/{body_rid[:2]}/{body_rid}.html" in http_names
    assert f"redirects/{redirect_rid[:2]}/{redirect_rid}.json" in http_names


def test_race_session_is_noop_without_archive_support(tmp_path: Path) -> None:
    cache = RedirectFetcher(tmp_path)
    original = cache.storage

    with cache.race_session("https://example.com/race/1") as scoped:
        assert scoped is original
        assert cache.storage is original

    assert cache.storage is original
