from typing import Any

from click.testing import CliRunner

import ranking.cli as cli_module


class DummyLog:
    def __init__(self) -> None:
        self.info_calls: list[tuple[str, dict[str, Any]]] = []

    def info(self, event: str, **kwargs: Any) -> None:
        self.info_calls.append((event, kwargs))

    def bind(self, **kwargs: Any) -> "DummyLog":
        return self

    def debug(self, event: str, **kwargs: Any) -> None:
        return None

    def warning(self, event: str, **kwargs: Any) -> None:
        return None

    def error(self, event: str, **kwargs: Any) -> None:
        return None


class DummyCache:
    def __init__(self) -> None:
        self.cache_hits = 4
        self.cache_misses = 1
        self.sleep_duration_seconds = 3

    def fetch(self, url: str, policy: Any) -> str:
        return "<html></html>"

    def save_extracted_json(self, url: str, data: Any) -> None:
        return None


def test_event_list_logs_final_crawl_summary(monkeypatch) -> None:
    cache = DummyCache()
    log = DummyLog()

    monkeypatch.setattr(
        cli_module,
        "extract_events_list",
        lambda html: {
            "events": [
                {
                    "name": "Event 1",
                    "url": "/event-1",
                    "date_raw": "2026-01-01",
                    "location_raw": "Rennes",
                }
            ],
            "next_url": None,
        },
    )
    monkeypatch.setattr(
        cli_module,
        "extract_event_detail",
        lambda html: {
            "event_race_raw": "Event 1",
            "races": [
                {
                    "source_url": "source/race-1",
                    "technical_url": "/race-1",
                    "name": "Race 1",
                    "ref_computed": "ref",
                    "heat_computed": "heat",
                }
            ],
        },
    )
    monkeypatch.setattr(
        cli_module,
        "extract_race_results",
        lambda html, race_information: {
            "results": [{"result_detail_url_computed": "/result-1"}],
            "next_url": None,
            "document": None,
        },
    )
    monkeypatch.setattr(cli_module, "extract_result_detail", lambda html: {"runner": "Alice"})
    monkeypatch.setattr(cli_module, "setup_logging", lambda debug=False: None)
    monkeypatch.setattr(cli_module.structlog, "get_logger", lambda: log)
    monkeypatch.setattr(cli_module, "HttpxCrawlerRuntime", lambda *args, **kwargs: cache)
    monotonic_values = iter([100.0, 106.0])
    monkeypatch.setattr(cli_module.time, "monotonic", lambda: next(monotonic_values))

    result = CliRunner().invoke(cli_module.cli, ["list"])
    assert result.exit_code == 0

    crawl_summary_calls = [fields for event, fields in log.info_calls if event == "crawl_summary"]
    assert len(crawl_summary_calls) == 1
    assert crawl_summary_calls[0] == {
        "wall_duration_seconds": 6,
        "sleep_duration_seconds": 3,
        "processing_duration_seconds": 3,
        "events_processed_count": 1,
        "events_failed_count": 0,
        "events_document_downloaded_count": 0,
        "events_document_failed_count": 0,
        "races_processed_count": 1,
        "races_external_count": 0,
        "races_failed_count": 0,
        "races_document_downloaded_count": 0,
        "races_document_failed_count": 0,
        "results_processed_count": 1,
        "results_failed_count": 0,
        "cache_hits_count": 4,
        "cache_misses_count": 1,
    }


def test_check_storage_local():
    runner = CliRunner()
    result = runner.invoke(
        cli_module.cli,
        ["check", "storage", "--storage", "local"],
    )

    assert result.exit_code == 0
    assert "SUCCESS" in result.output
