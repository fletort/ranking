from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

import ranking.cli as cli_module

# An optional page link the parser keeps but the HTTP client rejects (non-http scheme).
INVALID_URL = "javascript:void(0)"


class RecordingLog:
    """Logger stub accepting any structured event."""

    def __getattr__(self, name: str) -> Any:
        return lambda *args, **kwargs: None


class LinkCache:
    """Cache stub rejecting non-http URLs exactly like the real runtime does.

    Both :meth:`fetch` and :meth:`download` mimic the runtime guard, which raises ``ValueError``
    for a URL that is not an absolute ``http(s)`` URL (see ``normalize_url``).
    """

    def __init__(self) -> None:
        self.downloaded: list[str] = []

    @staticmethod
    def _reject_non_http(url: str) -> None:
        if not url.startswith("http"):
            raise ValueError(f"Invalid URL {url!r}: expected an absolute http:// or https:// URL")

    def fetch(self, url: str, policy: Any) -> str:
        self._reject_non_http(url)
        return "<html></html>"

    def download(self, url: str) -> None:
        self._reject_non_http(url)
        self.downloaded.append(url)

    def save_extracted_json(self, url: str, data: Any) -> None:
        return None

    @contextmanager
    def race_session(self, race_url: str) -> Iterator["LinkCache"]:
        yield self


def test_process_event_skips_empty_document_url_and_survives_an_invalid_link(monkeypatch) -> None:
    cache = LinkCache()
    summary = cli_module.CrawlSummary(started_at=0.0)
    processed_races: list[Any] = []

    monkeypatch.setattr(
        cli_module,
        "extract_event_detail",
        lambda html: {
            "event_race_raw": "Event",
            "races": [
                {
                    "source_url": "/race-source",
                    "technical_url": "/race-technical",
                    "name": "Race",
                    "ref_computed": "ref",
                    "heat_computed": "heat",
                }
            ],
            "documents": [
                {"url": "", "name": "empty href"},
                {"url": INVALID_URL, "name": "invalid href"},
                {"url": "/documents?name=ok.pdf", "name": "valid href"},
            ],
        },
    )
    monkeypatch.setattr(
        cli_module, "process_race", lambda *args, **kwargs: processed_races.append(args[0])
    )

    event: Any = {"name": "Event", "url": "/event-1", "date_raw": "", "location_raw": ""}
    cli_module.process_event(event, cache, RecordingLog(), summary=summary)

    # The empty href is skipped: the homepage is never downloaded as a document.
    assert cache.downloaded == ["https://resultats.breizhchrono.com/documents?name=ok.pdf"]
    assert summary.events_document_downloaded_count == 1
    # The invalid optional link is recorded as failed but does not abort the event.
    assert summary.events_document_failed_count == 1
    # Races are still processed after the bad link.
    assert len(processed_races) == 1


def test_process_event_records_failure_when_the_event_url_is_invalid() -> None:
    cache = LinkCache()
    summary = cli_module.CrawlSummary(started_at=0.0)
    event: Any = {"name": "Event", "url": INVALID_URL, "date_raw": "", "location_raw": ""}

    cli_module.process_event(event, cache, RecordingLog(), summary=summary)

    assert summary.events_failed_count == 1
    assert cache.downloaded == []


def test_process_race_survives_invalid_document_and_result_detail_links(monkeypatch) -> None:
    cache = LinkCache()
    summary = cli_module.CrawlSummary(started_at=0.0)
    race: Any = {
        "source_url": "/race-source",
        "technical_url": "/race-technical",
        "name": "Race",
        "ref_computed": "ref",
        "heat_computed": "heat",
    }

    monkeypatch.setattr(
        cli_module,
        "extract_race_results",
        lambda html, race_item: {
            "results": [{"result_detail_url_computed": INVALID_URL}],
            "next_url": None,
            "document": INVALID_URL,
        },
    )

    cli_module.process_race(race, cache, RecordingLog(), summary=summary)

    assert summary.races_document_failed_count == 1
    assert summary.results_failed_count == 1
    assert cache.downloaded == []
