from typing import Any

import pytest
from click.testing import CliRunner

import ranking.cli as cli_module

CHECKED_URL = "https://example.com/events?b=2&a=1"
# SHA-1 of the canonicalized URL (query parameters sorted): https://example.com/events?a=1&b=2
CHECKED_URL_RESOURCE_ID = "916737d101360f05f117a7336fbbbde916d93590"


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


# ---------------------------------------------------------------------------
# check resource-id
# ---------------------------------------------------------------------------


class DummyStorageProvider:
    """Minimal storage provider exposing the resource existence checks."""

    def __init__(self, http_cache_exists: bool = False, document_exists: bool = False) -> None:
        self._http_cache_exists = http_cache_exists
        self._document_exists = document_exists
        self.checked_urls: list[str] = []

    def exists_http_cache(self, url: str) -> bool:
        self.checked_urls.append(url)
        return self._http_cache_exists

    def document_exists(self, url: str) -> bool:
        self.checked_urls.append(url)
        return self._document_exists


def test_check_resource_id_displays_computed_id() -> None:
    result = CliRunner().invoke(cli_module.cli, ["check", "resource-id", "--url", CHECKED_URL])

    assert result.exit_code == 0
    assert f"URL : {CHECKED_URL}" in result.output
    assert f"Resource ID : {CHECKED_URL_RESOURCE_ID}" in result.output
    assert "You can specify storage backend and plugin to check for ressource." in result.output


@pytest.mark.parametrize(
    ("http_cache_exists", "document_exists", "expected_storage_area"),
    [
        (True, False, "HTTP Cache"),
        (False, True, "Document Cache"),
        (True, True, "HTTP Cache"),
    ],
    ids=["http-cache", "document-cache", "both"],
)
def test_check_resource_id_reports_present_resource(
    monkeypatch: pytest.MonkeyPatch,
    http_cache_exists: bool,
    document_exists: bool,
    expected_storage_area: str,
) -> None:
    storage_provider = DummyStorageProvider(http_cache_exists, document_exists)
    build_storage_calls: list[dict[str, str]] = []

    def fake_build_storage(storage_type: str, plugin_name: str) -> DummyStorageProvider:
        build_storage_calls.append({"storage_type": storage_type, "plugin_name": plugin_name})
        return storage_provider

    monkeypatch.setattr(cli_module, "build_storage", fake_build_storage)

    result = CliRunner().invoke(
        cli_module.cli,
        [
            "check",
            "resource-id",
            "--url",
            CHECKED_URL,
            "--storage",
            "local",
            "--plugin",
            "breizhchrono",
        ],
    )

    assert result.exit_code == 0
    assert "Present: yes" in result.output
    assert f"Storage Area: {expected_storage_area}" in result.output
    assert build_storage_calls == [{"storage_type": "local", "plugin_name": "breizhchrono"}]
    assert storage_provider.checked_urls == [CHECKED_URL, CHECKED_URL]


def test_check_resource_id_reports_absent_resource(monkeypatch: pytest.MonkeyPatch) -> None:
    storage_provider = DummyStorageProvider()
    monkeypatch.setattr(cli_module, "build_storage", lambda **kwargs: storage_provider)

    result = CliRunner().invoke(
        cli_module.cli,
        [
            "check",
            "resource-id",
            "--url",
            CHECKED_URL,
            "--storage",
            "local",
            "--plugin",
            "breizhchrono",
        ],
    )

    assert result.exit_code == 0
    assert "Present: no" in result.output
    assert "Storage Area:" not in result.output
    assert storage_provider.checked_urls == [CHECKED_URL, CHECKED_URL]
