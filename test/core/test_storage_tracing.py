from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from ranking.core.storage import (
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


# ---------------------------------------------------------------------------
# Trace emission
# ---------------------------------------------------------------------------


def test_save_http_cache_emits_http_cache_saved_trace(
    tracing: TracingStorageProvider, logger: MagicMock
) -> None:
    tracing.save_http_cache(TEST_URL, "<html>content</html>")

    logger.info.assert_called_once_with(
        "http_cache_saved",
        url=TEST_URL,
        resource_id=compute_resource_id(TEST_URL),
    )


def test_trace_resource_id_is_deterministic_across_url_variants(
    tracing: TracingStorageProvider, logger: MagicMock
) -> None:
    tracing.save_http_cache(TEST_URL, "v1")
    tracing.save_http_cache(TEST_URL_REORDERED, "v2")

    first = logger.info.call_args_list[0].kwargs["resource_id"]
    second = logger.info.call_args_list[1].kwargs["resource_id"]
    assert first == second


def test_no_trace_when_wrapped_write_fails(
    local: LocalStorageProvider, logger: MagicMock
) -> None:
    local.save_http_cache = MagicMock(side_effect=OSError("disk full"))  # type: ignore[method-assign]
    tracing = TracingStorageProvider(local, logger=logger)

    with pytest.raises(OSError):
        tracing.save_http_cache(TEST_URL, "content")

    logger.info.assert_not_called()


# ---------------------------------------------------------------------------
# Transparent delegation to the wrapped provider
# ---------------------------------------------------------------------------


def test_write_is_delegated_to_wrapped_provider(
    tracing: TracingStorageProvider, local: LocalStorageProvider
) -> None:
    tracing.save_http_cache(TEST_URL, "<html>content</html>")
    assert local.get_http_cache(TEST_URL) == "<html>content</html>"


def test_plugin_name_is_exposed(tracing: TracingStorageProvider) -> None:
    assert tracing.plugin_name == "myplugin"


def test_read_operations_are_delegated(
    tracing: TracingStorageProvider, logger: MagicMock
) -> None:
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
