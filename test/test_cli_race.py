from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

import ranking.cli as cli_module
from ranking.core.errors import ExternalRedirectError
from ranking.core.url import absolute_url


class DummyLog:
    """Logger stub accepting any structured event."""

    def __getattr__(self, name: str) -> Any:
        return lambda *args, **kwargs: None


class RecordingCache:
    """Minimal cache stub recording the race session scope."""

    def __init__(self) -> None:
        self.sessions: list[str] = []
        self.in_session = False

    @contextmanager
    def race_session(self, race_url: str) -> Iterator[Any]:
        self.sessions.append(race_url)
        self.in_session = True
        try:
            yield self
        finally:
            self.in_session = False

    def fetch(self, url: str, policy: Any) -> str:
        assert self.in_session, "race fetch must happen inside a race session"
        raise RuntimeError("stop the crawl")


class EventRecordingLog:
    """Logger stub recording the name of every structured event."""

    def __init__(self) -> None:
        self.events: list[str] = []

    def __getattr__(self, name: str) -> Any:
        def record(event: str, **kwargs: Any) -> None:
            self.events.append(event)

        return record

    def bind(self, **kwargs: Any) -> "EventRecordingLog":
        return self


class PagedRaceCache:
    """Minimal cache stub serving several paginated result pages of a single race."""

    def __init__(self) -> None:
        self.sessions: list[str] = []
        self.fetched: list[str] = []

    @contextmanager
    def race_session(self, race_url: str) -> Iterator[Any]:
        self.sessions.append(race_url)
        yield self

    def fetch(self, url: str, policy: Any) -> str:
        self.fetched.append(url)
        return "<html></html>"

    def save_extracted_json(self, url: str, data: Any) -> None:
        return None


class ExternalRedirectRaceCache:
    """Minimal cache stub whose race page redirects to another host."""

    @contextmanager
    def race_session(self, race_url: str) -> Iterator[Any]:
        yield self

    def fetch(self, url: str, policy: Any) -> str:
        raise ExternalRedirectError(requested_url=url, final_url="https://evil.example.com/race")


def test_process_race_opens_a_race_session_on_the_base_race_url() -> None:
    cache: Any = RecordingCache()
    race: Any = {"technical_url": "/event/1/race/2"}
    log: Any = DummyLog()

    cli_module.process_race(race, cache, log)

    assert cache.sessions == [absolute_url(cli_module.EVENTS_LIST_URL, "/event/1/race/2")]
    assert cache.in_session is False


def test_races_processed_counts_a_unique_race_once_across_paginated_result_pages(
    monkeypatch,
) -> None:
    cache: Any = PagedRaceCache()
    log: Any = EventRecordingLog()
    summary = cli_module.CrawlSummary(started_at=0.0)
    race: Any = {"technical_url": "/event/1/race/2"}
    pages = iter(
        [
            {"results": [], "next_url": "?page=2", "document": None},
            {"results": [], "next_url": "?page=3", "document": None},
            {"results": [], "next_url": None, "document": None},
        ]
    )
    monkeypatch.setattr(cli_module, "extract_race_results", lambda *args, **kwargs: next(pages))

    cli_module.process_race(race, cache, log, summary=summary)

    # The three paginated result pages belong to one race and must be counted as such.
    assert len(cache.fetched) == 3
    assert summary.races_processed_count == 1
    assert summary.result_pages_processed_count == 3
    # The race is traced once; page-level progress is traced separately.
    assert log.events.count("race_processed") == 1
    assert log.events.count("race_result_page_processed") == 3


def test_races_processed_is_not_counted_when_the_race_fetch_fails() -> None:
    cache: Any = RecordingCache()
    log: Any = EventRecordingLog()
    summary = cli_module.CrawlSummary(started_at=0.0)
    race: Any = {"technical_url": "/event/1/race/2"}

    cli_module.process_race(race, cache, log, summary=summary)

    assert summary.races_processed_count == 0
    assert summary.races_failed_count == 1
    assert "race_processed" not in log.events


def test_races_processed_is_not_counted_when_the_race_redirects_externally() -> None:
    cache: Any = ExternalRedirectRaceCache()
    log: Any = EventRecordingLog()
    summary = cli_module.CrawlSummary(started_at=0.0)
    race: Any = {"technical_url": "/event/1/race/2"}

    cli_module.process_race(race, cache, log, summary=summary)

    assert summary.races_processed_count == 0
    assert summary.races_external_count == 1
    assert "race_processed" not in log.events
