from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from ranking.core.storage import (
    DownloadedDocument,
    LocalStorageProvider,
    TracingStorageProvider,
    compute_resource_id,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TEST_URL = "https://example.com/events?year=2025&page=1"
TEST_URL_REORDERED = "https://example.com/events?page=1&year=2025"


@pytest.fixture()
def local(tmp_path: Path) -> LocalStorageProvider:
    return LocalStorageProvider(
        "myplugin", cache_root=tmp_path / ".cache", document_root=tmp_path / ".documents"
    )


@pytest.fixture()
def logger() -> MagicMock:
    return MagicMock()


@pytest.fixture()
def tracing(local: LocalStorageProvider, logger: MagicMock) -> TracingStorageProvider:
    return TracingStorageProvider(local, logger=logger)


def _document(url: str = TEST_URL) -> DownloadedDocument:
    content = b"pdf-content"
    return DownloadedDocument(
        url=url,
        content=content,
        original_filename="race.pdf",
        content_type="application/pdf",
        content_length=len(content),
        downloaded_at=datetime.now(),
    )


# ---------------------------------------------------------------------------
# Trace emission
# ---------------------------------------------------------------------------


def test_save_http_cache_emits_cache_saved_trace(
    tracing: TracingStorageProvider, logger: MagicMock
) -> None:
    tracing.save_http_cache(TEST_URL, "<html>content</html>")

    logger.info.assert_called_once_with(
        "cache_saved",
        url=TEST_URL,
        resource_id=compute_resource_id(TEST_URL),
    )


def test_save_http_snapshot_emits_snapshot_saved_trace(
    tracing: TracingStorageProvider, logger: MagicMock
) -> None:
    timestamp = "2026-01-01T00-00-00-000000"

    tracing.save_http_snapshot(TEST_URL, "<html>content</html>", timestamp)

    logger.info.assert_called_once_with(
        "snapshot_saved",
        url=TEST_URL,
        resource_id=compute_resource_id(TEST_URL),
    )


def test_save_extracted_emits_extracted_json_saved_trace(
    tracing: TracingStorageProvider, logger: MagicMock
) -> None:
    tracing.save_extracted(TEST_URL, {"key": "value"})

    logger.info.assert_called_once_with(
        "extracted_json_saved",
        url=TEST_URL,
        resource_id=compute_resource_id(TEST_URL),
    )


def test_save_document_emits_document_saved_trace(
    tracing: TracingStorageProvider, logger: MagicMock
) -> None:
    document = _document()

    tracing.save_document(document)

    logger.info.assert_called_once_with(
        "document_saved",
        url=document.url,
        resource_id=compute_resource_id(document.url),
    )


def test_trace_uses_wrapped_provider_identity(tmp_path: Path, logger: MagicMock) -> None:
    """The traced resource ID must come from the wrapped provider's identity method."""

    class FixedIdentityProvider(LocalStorageProvider):
        def _compute_resource_id(self, url: str) -> str:
            return "custom-resource-id"

    provider = FixedIdentityProvider("myplugin", cache_root=tmp_path / ".cache")
    tracing = TracingStorageProvider(provider, logger=logger)

    tracing.save_http_cache(TEST_URL, "<html>content</html>")

    logger.info.assert_called_once_with(
        "cache_saved",
        url=TEST_URL,
        resource_id="custom-resource-id",
    )


def test_trace_resource_id_is_deterministic_across_url_variants(
    tracing: TracingStorageProvider, logger: MagicMock
) -> None:
    tracing.save_http_cache(TEST_URL, "v1")
    tracing.save_http_cache(TEST_URL_REORDERED, "v2")

    first = logger.info.call_args_list[0].kwargs["resource_id"]
    second = logger.info.call_args_list[1].kwargs["resource_id"]
    assert first == second


@pytest.mark.parametrize(
    ("method_name", "args"),
    [
        ("save_http_cache", (TEST_URL, "content")),
        ("save_http_snapshot", (TEST_URL, "content", "2026-01-01T00-00-00-000000")),
        ("save_extracted", (TEST_URL, {"key": "value"})),
        ("save_document", (_document(),)),
    ],
)
def test_no_trace_when_wrapped_write_fails(
    local: LocalStorageProvider,
    logger: MagicMock,
    method_name: str,
    args: tuple,
) -> None:
    setattr(local, method_name, MagicMock(side_effect=OSError("disk full")))
    tracing = TracingStorageProvider(local, logger=logger)

    with pytest.raises(OSError):
        getattr(tracing, method_name)(*args)

    logger.info.assert_not_called()


# ---------------------------------------------------------------------------
# Transparent delegation to the wrapped provider
# ---------------------------------------------------------------------------


def test_write_is_delegated_to_wrapped_provider(
    tracing: TracingStorageProvider, local: LocalStorageProvider
) -> None:
    tracing.save_http_cache(TEST_URL, "<html>content</html>")
    assert local.get_http_cache(TEST_URL) == "<html>content</html>"


def test_snapshot_write_is_delegated_to_wrapped_provider(
    tracing: TracingStorageProvider, local: LocalStorageProvider
) -> None:
    timestamp = "2026-01-01T00-00-00-000000"
    tracing.save_http_snapshot(TEST_URL, "<html>content</html>", timestamp)
    assert local.list_http_snapshots(TEST_URL) == [(timestamp, "<html>content</html>")]


def test_extracted_write_is_delegated_to_wrapped_provider(
    tracing: TracingStorageProvider, local: LocalStorageProvider
) -> None:
    tracing.save_extracted(TEST_URL, {"key": "value"})
    assert local.get_extracted(TEST_URL) == {"key": "value"}


def test_document_write_is_delegated_to_wrapped_provider(
    tracing: TracingStorageProvider, local: LocalStorageProvider
) -> None:
    document = _document()
    tracing.save_document(document)
    assert local.document_exists(document.url) is True


def test_plugin_name_is_exposed(tracing: TracingStorageProvider) -> None:
    assert tracing.plugin_name == "myplugin"


def test_read_operations_are_delegated(tracing: TracingStorageProvider, logger: MagicMock) -> None:
    tracing.save_http_cache(TEST_URL, "<html>content</html>")
    logger.info.reset_mock()

    assert tracing.get_http_cache(TEST_URL) == "<html>content</html>"
    assert tracing.exists_http_cache(TEST_URL) is True
    assert tracing.exists_http_cache("https://example.com/missing") is False
    assert tracing.get_extracted(TEST_URL) is None
    assert tracing.document_exists(TEST_URL) is False

    logger.info.assert_not_called()


def test_healthcheck_is_delegated(tracing: TracingStorageProvider) -> None:
    result = tracing.healthcheck()
    assert result.backend == "local"
