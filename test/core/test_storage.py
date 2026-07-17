from __future__ import annotations

import json
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

from ranking.core.storage import LocalStorageProvider, S3StorageProvider

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TEST_URL = "https://example.com/events?year=2025&page=1"
TEST_URL_REORDERED = "https://example.com/events?page=1&year=2025"
TEST_URL_DIFFERENT = "https://example.com/other"


@pytest.fixture()
def local(tmp_path: Path) -> LocalStorageProvider:
    return LocalStorageProvider(
        "myplugin", cache_root=tmp_path / ".cache", document_root=tmp_path / ".documents"
    )


@pytest.fixture()
def s3_provider():
    with mock_aws():
        client = boto3.client("s3", region_name="eu-west-1")
        client.create_bucket(
            Bucket="ranking",
            CreateBucketConfiguration={"LocationConstraint": "eu-west-1"},
        )
        yield S3StorageProvider("myplugin", bucket="ranking", region="eu-west-1")


# ---------------------------------------------------------------------------
# Resource ID tests (shared behavior via StorageProvider base)
# ---------------------------------------------------------------------------


def test_resource_id_same_url_is_deterministic(local: LocalStorageProvider) -> None:
    rid1 = local._compute_resource_id(TEST_URL)
    rid2 = local._compute_resource_id(TEST_URL)
    assert rid1 == rid2


def test_resource_id_ignores_query_parameter_order(local: LocalStorageProvider) -> None:
    rid1 = local._compute_resource_id(TEST_URL)
    rid2 = local._compute_resource_id(TEST_URL_REORDERED)
    assert rid1 == rid2


def test_resource_id_differs_for_different_urls(local: LocalStorageProvider) -> None:
    rid1 = local._compute_resource_id(TEST_URL)
    rid2 = local._compute_resource_id(TEST_URL_DIFFERENT)
    assert rid1 != rid2


def test_resource_id_is_sha1_hex(local: LocalStorageProvider) -> None:
    import hashlib
    from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

    url = "https://example.com/page?b=2&a=1"
    parsed = urlparse(url)
    sorted_query = sorted(parse_qsl(parsed.query, keep_blank_values=True))
    canonical_query = urlencode(sorted_query, doseq=True)
    canonical = urlunparse(
        (parsed.scheme, parsed.netloc, parsed.path, parsed.params, canonical_query, parsed.fragment)
    )
    expected = hashlib.sha1(canonical.encode("utf-8")).hexdigest()  # noqa: S324
    assert local._compute_resource_id(url) == expected


# ---------------------------------------------------------------------------
# LocalStorageProvider — HTTP cache
# ---------------------------------------------------------------------------


def test_local_save_and_get_http_cache(local: LocalStorageProvider) -> None:
    local.save_http_cache(TEST_URL, "<html>hello</html>")
    assert local.get_http_cache(TEST_URL) == "<html>hello</html>"


def test_local_get_http_cache_returns_none_when_missing(local: LocalStorageProvider) -> None:
    assert local.get_http_cache(TEST_URL) is None


def test_local_exists_http_cache(local: LocalStorageProvider) -> None:
    assert not local.exists_http_cache(TEST_URL)
    local.save_http_cache(TEST_URL, "content")
    assert local.exists_http_cache(TEST_URL)


def test_local_http_cache_url_canonicalization(local: LocalStorageProvider) -> None:
    local.save_http_cache(TEST_URL, "v1")
    assert local.get_http_cache(TEST_URL_REORDERED) == "v1"


def test_local_http_cache_path_sharding(local: LocalStorageProvider, tmp_path: Path) -> None:
    local.save_http_cache(TEST_URL, "content")
    rid = local._compute_resource_id(TEST_URL)
    shard = rid[:2]
    expected = tmp_path / ".cache" / "myplugin" / "http" / "current" / shard / f"{rid}.html"
    assert expected.exists()


# ---------------------------------------------------------------------------
# LocalStorageProvider — Snapshots
# ---------------------------------------------------------------------------


def test_local_save_and_list_snapshots(local: LocalStorageProvider) -> None:
    local.save_http_snapshot(TEST_URL, "v1", "2026-01-01T00-00-00-000000")
    local.save_http_snapshot(TEST_URL, "v2", "2026-01-02T00-00-00-000000")
    snapshots = local.list_http_snapshots(TEST_URL)
    assert len(snapshots) == 2
    assert snapshots[0] == ("2026-01-01T00-00-00-000000", "v1")
    assert snapshots[1] == ("2026-01-02T00-00-00-000000", "v2")


def test_local_list_snapshots_returns_empty_when_none(local: LocalStorageProvider) -> None:
    assert local.list_http_snapshots(TEST_URL) == []


def test_local_snapshots_are_sorted_by_timestamp(local: LocalStorageProvider) -> None:
    local.save_http_snapshot(TEST_URL, "b", "2026-01-02T00-00-00-000000")
    local.save_http_snapshot(TEST_URL, "a", "2026-01-01T00-00-00-000000")
    snapshots = local.list_http_snapshots(TEST_URL)
    assert [ts for ts, _ in snapshots] == [
        "2026-01-01T00-00-00-000000",
        "2026-01-02T00-00-00-000000",
    ]


# ---------------------------------------------------------------------------
# LocalStorageProvider — Extracted data
# ---------------------------------------------------------------------------


def test_local_save_and_get_extracted(local: LocalStorageProvider) -> None:
    data = {"races": [1, 2, 3]}
    local.save_extracted(TEST_URL, data)
    assert local.get_extracted(TEST_URL) == data


def test_local_get_extracted_returns_none_when_missing(local: LocalStorageProvider) -> None:
    assert local.get_extracted(TEST_URL) is None


def test_local_extracted_is_indented_json(local: LocalStorageProvider) -> None:
    local.save_extracted(TEST_URL, {"key": "value"})
    raw = local._extracted_path(TEST_URL).read_text(encoding="utf-8")
    assert "\n" in raw
    assert "  " in raw


def test_local_extracted_url_canonicalization(local: LocalStorageProvider) -> None:
    local.save_extracted(TEST_URL, {"x": 1})
    assert local.get_extracted(TEST_URL_REORDERED) == {"x": 1}


def test_local_extracted_path_sharding(local: LocalStorageProvider, tmp_path: Path) -> None:
    local.save_extracted(TEST_URL, {"k": "v"})
    rid = local._compute_resource_id(TEST_URL)
    shard = rid[:2]
    expected = tmp_path / ".cache" / "myplugin" / "extracted" / shard / f"{rid}.json"
    assert expected.exists()


# ---------------------------------------------------------------------------
# LocalStorageProvider — Documents
# ---------------------------------------------------------------------------


def test_local_save_and_get_document(local: LocalStorageProvider) -> None:
    content = b"%PDF-1.7"
    metadata = {
        "key": "abc",
        "url": TEST_URL,
        "original_filename": "race.pdf",
        "content_type": "application/pdf",
        "content_length": len(content),
        "downloaded_at": "2026-01-01T00:00:00+00:00",
    }
    local.save_document(TEST_URL, content, metadata)
    result = local.get_document(TEST_URL)
    assert result is not None
    returned_content, returned_meta = result
    assert returned_content == content
    assert returned_meta["original_filename"] == "race.pdf"


def test_local_document_exists(local: LocalStorageProvider) -> None:
    assert not local.document_exists(TEST_URL)
    local.save_document(TEST_URL, b"data", {"original_filename": "f.pdf"})
    assert local.document_exists(TEST_URL)


def test_local_get_document_returns_none_when_missing(local: LocalStorageProvider) -> None:
    assert local.get_document(TEST_URL) is None


def test_local_document_path_sharding(local: LocalStorageProvider, tmp_path: Path) -> None:
    local.save_document(TEST_URL, b"data", {"original_filename": "f.pdf"})
    rid = local._compute_resource_id(TEST_URL)
    shard = rid[:2]
    expected_dir = tmp_path / ".documents" / "myplugin" / shard / rid
    assert (expected_dir / "f.pdf").exists()
    assert (expected_dir / "metadata.json").exists()


# ---------------------------------------------------------------------------
# LocalStorageProvider — plugin name isolation
# ---------------------------------------------------------------------------


def test_local_plugin_name_isolation(tmp_path: Path) -> None:
    provider_a = LocalStorageProvider("plugin_a", cache_root=tmp_path)
    provider_b = LocalStorageProvider("plugin_b", cache_root=tmp_path)

    provider_a.save_http_cache(TEST_URL, "from-a")
    assert provider_a.get_http_cache(TEST_URL) == "from-a"
    assert provider_b.get_http_cache(TEST_URL) is None


# ---------------------------------------------------------------------------
# S3StorageProvider — HTTP cache
# ---------------------------------------------------------------------------


def test_s3_save_and_get_http_cache(s3_provider: S3StorageProvider) -> None:
    s3_provider.save_http_cache(TEST_URL, "<html>s3</html>")
    assert s3_provider.get_http_cache(TEST_URL) == "<html>s3</html>"


def test_s3_get_http_cache_returns_none_when_missing(s3_provider: S3StorageProvider) -> None:
    assert s3_provider.get_http_cache(TEST_URL) is None


def test_s3_exists_http_cache(s3_provider: S3StorageProvider) -> None:
    assert not s3_provider.exists_http_cache(TEST_URL)
    s3_provider.save_http_cache(TEST_URL, "content")
    assert s3_provider.exists_http_cache(TEST_URL)


def test_s3_http_cache_url_canonicalization(s3_provider: S3StorageProvider) -> None:
    s3_provider.save_http_cache(TEST_URL, "canonical")
    assert s3_provider.get_http_cache(TEST_URL_REORDERED) == "canonical"


def test_s3_http_cache_key_sharding(s3_provider: S3StorageProvider) -> None:
    s3_provider.save_http_cache(TEST_URL, "content")
    rid = s3_provider._compute_resource_id(TEST_URL)
    shard = rid[:2]
    expected_key = f"myplugin/cache/http/current/{shard}/{rid}.html"
    assert s3_provider._http_cache_key(TEST_URL) == expected_key


# ---------------------------------------------------------------------------
# S3StorageProvider — Snapshots
# ---------------------------------------------------------------------------


def test_s3_save_and_list_snapshots(s3_provider: S3StorageProvider) -> None:
    s3_provider.save_http_snapshot(TEST_URL, "v1", "2026-01-01T00-00-00-000000")
    s3_provider.save_http_snapshot(TEST_URL, "v2", "2026-01-02T00-00-00-000000")
    snapshots = s3_provider.list_http_snapshots(TEST_URL)
    assert len(snapshots) == 2
    assert snapshots[0] == ("2026-01-01T00-00-00-000000", "v1")
    assert snapshots[1] == ("2026-01-02T00-00-00-000000", "v2")


def test_s3_list_snapshots_returns_empty_when_none(s3_provider: S3StorageProvider) -> None:
    assert s3_provider.list_http_snapshots(TEST_URL) == []


# ---------------------------------------------------------------------------
# S3StorageProvider — Extracted data
# ---------------------------------------------------------------------------


def test_s3_save_and_get_extracted(s3_provider: S3StorageProvider) -> None:
    data = {"results": [1, 2]}
    s3_provider.save_extracted(TEST_URL, data)
    assert s3_provider.get_extracted(TEST_URL) == data


def test_s3_get_extracted_returns_none_when_missing(s3_provider: S3StorageProvider) -> None:
    assert s3_provider.get_extracted(TEST_URL) is None


def test_s3_extracted_key_sharding(s3_provider: S3StorageProvider) -> None:
    rid = s3_provider._compute_resource_id(TEST_URL)
    shard = rid[:2]
    expected_key = f"myplugin/cache/extracted/{shard}/{rid}.json"
    assert s3_provider._extracted_key(TEST_URL) == expected_key


# ---------------------------------------------------------------------------
# S3StorageProvider — Documents
# ---------------------------------------------------------------------------


def test_s3_save_and_get_document(s3_provider: S3StorageProvider) -> None:
    content = b"%PDF-1.7"
    metadata = {
        "key": "abc",
        "url": TEST_URL,
        "original_filename": "race.pdf",
        "content_type": "application/pdf",
        "content_length": len(content),
        "downloaded_at": "2026-01-01T00:00:00+00:00",
    }
    s3_provider.save_document(TEST_URL, content, metadata)
    result = s3_provider.get_document(TEST_URL)
    assert result is not None
    returned_content, returned_meta = result
    assert returned_content == content
    assert returned_meta["original_filename"] == "race.pdf"


def test_s3_document_exists(s3_provider: S3StorageProvider) -> None:
    assert not s3_provider.document_exists(TEST_URL)
    s3_provider.save_document(TEST_URL, b"data", {"original_filename": "f.pdf"})
    assert s3_provider.document_exists(TEST_URL)


def test_s3_get_document_returns_none_when_missing(s3_provider: S3StorageProvider) -> None:
    assert s3_provider.get_document(TEST_URL) is None


def test_s3_document_key_sharding(s3_provider: S3StorageProvider) -> None:
    rid = s3_provider._compute_resource_id(TEST_URL)
    shard = rid[:2]
    expected_prefix = f"myplugin/documents/{shard}/{rid}/"
    assert s3_provider._document_prefix(TEST_URL) == expected_prefix


def test_s3_document_metadata_stored_as_dedicated_object(s3_provider: S3StorageProvider) -> None:
    metadata = {
        "original_filename": "race.pdf",
        "content_type": "application/pdf",
        "content_length": 100,
        "downloaded_at": "2026-01-01T00:00:00+00:00",
    }
    s3_provider.save_document(TEST_URL, b"content", metadata)
    meta_key = s3_provider._document_metadata_key(TEST_URL)
    response = boto3.client("s3", region_name="eu-west-1").get_object(
        Bucket="ranking", Key=meta_key
    )
    stored_meta = json.loads(response["Body"].read().decode("utf-8"))
    assert stored_meta["original_filename"] == "race.pdf"


# ---------------------------------------------------------------------------
# S3StorageProvider — plugin name isolation
# ---------------------------------------------------------------------------


def test_s3_plugin_name_isolation() -> None:
    with mock_aws():
        client = boto3.client("s3", region_name="eu-west-1")
        client.create_bucket(
            Bucket="ranking",
            CreateBucketConfiguration={"LocationConstraint": "eu-west-1"},
        )
        provider_a = S3StorageProvider("plugin_a", bucket="ranking", region="eu-west-1")
        provider_b = S3StorageProvider("plugin_b", bucket="ranking", region="eu-west-1")

        provider_a.save_http_cache(TEST_URL, "from-a")
        assert provider_a.get_http_cache(TEST_URL) == "from-a"
        assert provider_b.get_http_cache(TEST_URL) is None


# ---------------------------------------------------------------------------
# Integration: HttpxClientWithCache with S3StorageProvider
# ---------------------------------------------------------------------------


def test_httpx_cache_with_s3_storage() -> None:
    """Verify HttpxClientWithCache works end-to-end with S3StorageProvider."""
    from unittest.mock import patch

    import httpx as _httpx

    from ranking.core.cache import CachePolicy
    from ranking.core.cache_httpx import HttpxClientWithCache

    with mock_aws():
        client = boto3.client("s3", region_name="eu-west-1")
        client.create_bucket(
            Bucket="ranking",
            CreateBucketConfiguration={"LocationConstraint": "eu-west-1"},
        )
        storage = S3StorageProvider("myplugin", bucket="ranking", region="eu-west-1")
        cache = HttpxClientWithCache(plugin_name="myplugin", storage=storage)

        calls: list[str] = []

        def fake_get(*args, **kwargs):
            url = str(args[0]) if args else str(kwargs["url"])
            calls.append(url)
            return _httpx.Response(
                200, text="<html>s3 content</html>", request=_httpx.Request("GET", url)
            )

        url = "https://example.com/events"
        with patch("ranking.core.cache_httpx.httpx.get", fake_get):
            first = cache.fetch(url, CachePolicy.CACHE_IF_PRESENT)
            second = cache.fetch(url, CachePolicy.CACHE_IF_PRESENT)

        assert first == "<html>s3 content</html>"
        assert second == "<html>s3 content</html>"
        assert calls == [url]
        assert storage.exists_http_cache(url)
