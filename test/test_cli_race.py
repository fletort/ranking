from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

import ranking.cli as cli_module


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


def test_process_race_opens_a_race_session_on_the_base_race_url() -> None:
    cache: Any = RecordingCache()
    race: Any = {"technical_url": "/event/1/race/2"}
    log: Any = DummyLog()

    cli_module.process_race(race, cache, log)

    assert cache.sessions == [cli_module.EVENTS_LIST_URL + "/event/1/race/2"]
    assert cache.in_session is False
