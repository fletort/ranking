from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator
from urllib.parse import urlparse

import ranking.cli as cli_module
from ranking.core.errors import ExternalRedirectError

# An optional page link the parser keeps but the HTTP client rejects (non-http scheme).
INVALID_URL = "javascript:void(0)"
# An optional page link to another host: refused by the runtime's ``_ensure_allowed_host`` guard.
OFF_HOST_URL = "https://evil.example.com/document.pdf"
# A URL so malformed that resolving it raises ValueError (Invalid IPv6 URL).
MALFORMED_URL = "https://[broken/event"
ALLOWED_HOST = "resultats.breizhchrono.com"


class RecordingLog:
    """Logger stub accepting any structured event."""

    def __getattr__(self, name: str) -> Any:
        return lambda *args, **kwargs: None

    def bind(self, **kwargs: Any) -> "RecordingLog":
        return self


class LinkCache:
    """Cache stub mimicking the URL guards the real runtime applies before any network access.

    :meth:`fetch` and :meth:`download` raise ``ValueError`` for a URL that is not an absolute
    ``http(s)`` URL (``validate_http_scheme``) and ``ExternalRedirectError`` for a URL outside the
    crawled host (``_ensure_allowed_host``).
    """

    def __init__(self) -> None:
        self.downloaded: list[str] = []
        self.sessions: list[str] = []

    @staticmethod
    def _reject(url: str) -> None:
        if not url.startswith("http"):
            raise ValueError(f"Invalid URL {url!r}: expected an absolute http:// or https:// URL")
        if urlparse(url).netloc != ALLOWED_HOST:
            raise ExternalRedirectError(requested_url=url, final_url=url)

    def fetch(self, url: str, policy: Any) -> str:
        self._reject(url)
        return "<html></html>"

    def download(self, url: str) -> None:
        self._reject(url)
        self.downloaded.append(url)

    def save_extracted_json(self, url: str, data: Any) -> None:
        return None

    @contextmanager
    def race_session(self, race_url: str) -> Iterator["LinkCache"]:
        self.sessions.append(race_url)
        yield self


def test_process_event_skips_empty_document_url_and_survives_an_invalid_link(monkeypatch) -> None:
    cache: Any = LinkCache()
    log: Any = RecordingLog()
    summary = cli_module.CrawlSummary(started_at=0.0)
    processed_races: list[Any] = []

    monkeypatch.setattr(
        cli_module,
        "extract_event_detail",
        lambda html, log=None: {
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
    cli_module.process_event(event, cache, log, summary=summary)

    # The empty href is skipped: the homepage is never downloaded as a document.
    assert cache.downloaded == ["https://resultats.breizhchrono.com/documents?name=ok.pdf"]
    assert summary.events_document_downloaded_count == 1
    # The invalid optional link is recorded as failed but does not abort the event.
    assert summary.events_document_failed_count == 1
    # Races are still processed after the bad link.
    assert len(processed_races) == 1


def test_process_event_records_failure_when_the_event_url_is_invalid() -> None:
    cache: Any = LinkCache()
    log: Any = RecordingLog()
    summary = cli_module.CrawlSummary(started_at=0.0)
    event: Any = {"name": "Event", "url": INVALID_URL, "date_raw": "", "location_raw": ""}

    cli_module.process_event(event, cache, log, summary=summary)

    assert summary.events_failed_count == 1
    assert cache.downloaded == []


def test_process_race_survives_invalid_document_and_result_detail_links(monkeypatch) -> None:
    cache: Any = LinkCache()
    log: Any = RecordingLog()
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
        lambda html, race_item, log=None: {
            "results": [{"result_detail_url_computed": INVALID_URL}],
            "next_url": None,
            "document": INVALID_URL,
        },
    )

    cli_module.process_race(race, cache, log, summary=summary)

    assert summary.races_document_failed_count == 1
    assert summary.results_failed_count == 1
    assert cache.downloaded == []


def test_process_event_counts_an_off_host_document_as_failed_without_aborting(monkeypatch) -> None:
    cache: Any = LinkCache()
    log: Any = RecordingLog()
    summary = cli_module.CrawlSummary(started_at=0.0)
    processed_races: list[Any] = []

    monkeypatch.setattr(
        cli_module,
        "extract_event_detail",
        lambda html, log=None: {
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
            "documents": [{"url": OFF_HOST_URL, "name": "off host"}],
        },
    )
    monkeypatch.setattr(
        cli_module, "process_race", lambda *args, **kwargs: processed_races.append(args[0])
    )

    event: Any = {"name": "Event", "url": "/event-1", "date_raw": "", "location_raw": ""}
    cli_module.process_event(event, cache, log, summary=summary)

    # The refused off-host document is recorded as failed and must not abort the event.
    assert summary.events_document_failed_count == 1
    assert cache.downloaded == []
    assert len(processed_races) == 1


def test_process_race_counts_an_off_host_document_as_failed_without_aborting(monkeypatch) -> None:
    cache: Any = LinkCache()
    log: Any = RecordingLog()
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
        lambda html, race_item, log=None: {
            "results": [],
            "next_url": None,
            "document": OFF_HOST_URL,
        },
    )

    cli_module.process_race(race, cache, log, summary=summary)

    assert summary.races_document_failed_count == 1
    assert cache.downloaded == []


def test_process_event_counts_a_malformed_event_url_as_failed_without_aborting() -> None:
    cache: Any = LinkCache()
    log: Any = RecordingLog()
    summary = cli_module.CrawlSummary(started_at=0.0)
    event: Any = {"name": "Event", "url": MALFORMED_URL, "date_raw": "", "location_raw": ""}

    cli_module.process_event(event, cache, log, summary=summary)

    assert summary.events_failed_count == 1


def test_process_race_counts_a_malformed_race_url_as_failed_without_opening_a_session() -> None:
    cache: Any = LinkCache()
    log: Any = RecordingLog()
    summary = cli_module.CrawlSummary(started_at=0.0)
    race: Any = {"technical_url": MALFORMED_URL}

    cli_module.process_race(race, cache, log, summary=summary)

    assert summary.races_failed_count == 1
    # The race session must not be opened for a link that cannot be resolved.
    assert cache.sessions == []


def test_process_race_counts_a_malformed_export_url_as_failed_without_aborting(monkeypatch) -> None:
    cache: Any = LinkCache()
    log: Any = RecordingLog()
    summary = cli_module.CrawlSummary(started_at=0.0)
    race: Any = {"technical_url": "/race-technical"}

    monkeypatch.setattr(
        cli_module,
        "extract_race_results",
        lambda html, race_item, log=None: {
            "results": [],
            "next_url": None,
            "document": MALFORMED_URL,
        },
    )

    cli_module.process_race(race, cache, log, summary=summary)

    assert summary.races_document_failed_count == 1
    assert cache.sessions == ["https://resultats.breizhchrono.com/race-technical"]
