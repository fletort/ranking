from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

from ranking.core.storage import DownloadedDocument, LocalStorageProvider, S3StorageProvider

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


@pytest.fixture(params=["local", "s3"])
def storage_provider(request, local, s3_provider):
    """Parametrized fixture that provides both LocalStorage and S3Storage."""
    if request.param == "local":
        return local
    return s3_provider


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
# Shared tests — HTTP cache (parametrized across LocalStorage and S3Storage)
# ---------------------------------------------------------------------------


def test_save_and_get_http_cache(storage_provider) -> None:
    storage_provider.save_http_cache(TEST_URL, "<html>hello</html>")
    assert storage_provider.get_http_cache(TEST_URL) == "<html>hello</html>"


def test_get_http_cache_returns_none_when_missing(storage_provider) -> None:
    assert storage_provider.get_http_cache(TEST_URL) is None


def test_exists_http_cache(storage_provider) -> None:
    assert not storage_provider.exists_http_cache(TEST_URL)
    storage_provider.save_http_cache(TEST_URL, "content")
    assert storage_provider.exists_http_cache(TEST_URL)


def test_http_cache_url_canonicalization(storage_provider) -> None:
    storage_provider.save_http_cache(TEST_URL, "v1")
    assert storage_provider.get_http_cache(TEST_URL_REORDERED) == "v1"


# ---------------------------------------------------------------------------
# LocalStorageProvider — HTTP cache (implementation-specific tests)
# ---------------------------------------------------------------------------


def test_local_http_cache_path_sharding(local: LocalStorageProvider, tmp_path: Path) -> None:
    local.save_http_cache(TEST_URL, "content")
    rid = local._compute_resource_id(TEST_URL)
    shard = rid[:2]
    expected = tmp_path / ".cache" / "myplugin" / "http" / "current" / shard / f"{rid}.html"
    assert expected.exists()


# ---------------------------------------------------------------------------
# Shared tests — Snapshots (parametrized across LocalStorage and S3Storage)
# ---------------------------------------------------------------------------


def test_save_and_list_snapshots(storage_provider) -> None:
    storage_provider.save_http_snapshot(TEST_URL, "v1", "2026-01-01T00-00-00-000000")
    storage_provider.save_http_snapshot(TEST_URL, "v2", "2026-01-02T00-00-00-000000")
    snapshots = storage_provider.list_http_snapshots(TEST_URL)
    assert len(snapshots) == 2
    assert snapshots[0] == ("2026-01-01T00-00-00-000000", "v1")
    assert snapshots[1] == ("2026-01-02T00-00-00-000000", "v2")


def test_list_snapshots_returns_empty_when_none(storage_provider) -> None:
    assert storage_provider.list_http_snapshots(TEST_URL) == []


# ---------------------------------------------------------------------------
# LocalStorageProvider — Snapshots (implementation-specific tests)
# ---------------------------------------------------------------------------


def test_local_snapshots_are_sorted_by_timestamp(local: LocalStorageProvider) -> None:
    local.save_http_snapshot(TEST_URL, "b", "2026-01-02T00-00-00-000000")
    local.save_http_snapshot(TEST_URL, "a", "2026-01-01T00-00-00-000000")
    snapshots = local.list_http_snapshots(TEST_URL)
    assert [ts for ts, _ in snapshots] == [
        "2026-01-01T00-00-00-000000",
        "2026-01-02T00-00-00-000000",
    ]


# ---------------------------------------------------------------------------
# Shared tests — Extracted data (parametrized across LocalStorage and S3Storage)
# ---------------------------------------------------------------------------


def test_save_and_get_extracted(storage_provider) -> None:
    data = {"races": [1, 2, 3]}
    storage_provider.save_extracted(TEST_URL, data)
    assert storage_provider.get_extracted(TEST_URL) == data


def test_get_extracted_returns_none_when_missing(storage_provider) -> None:
    assert storage_provider.get_extracted(TEST_URL) is None


def test_extracted_url_canonicalization(storage_provider) -> None:
    storage_provider.save_extracted(TEST_URL, {"x": 1})
    assert storage_provider.get_extracted(TEST_URL_REORDERED) == {"x": 1}


# ---------------------------------------------------------------------------
# LocalStorageProvider — Extracted data (implementation-specific tests)
# ---------------------------------------------------------------------------


def test_local_extracted_is_indented_json(local: LocalStorageProvider) -> None:
    local.save_extracted(TEST_URL, {"key": "value"})
    raw = local._extracted_path(TEST_URL).read_text(encoding="utf-8")
    assert "\n" in raw
    assert "  " in raw


def test_local_extracted_path_sharding(local: LocalStorageProvider, tmp_path: Path) -> None:
    local.save_extracted(TEST_URL, {"k": "v"})
    rid = local._compute_resource_id(TEST_URL)
    shard = rid[:2]
    expected = tmp_path / ".cache" / "myplugin" / "extracted" / shard / f"{rid}.json"
    assert expected.exists()


# ---------------------------------------------------------------------------
# Shared tests — Documents (parametrized across LocalStorage and S3Storage)
# ---------------------------------------------------------------------------


def test_save_and_get_document(storage_provider) -> None:
    content = b"%PDF-1.7"
    document = DownloadedDocument(
        url=TEST_URL,
        content=content,
        original_filename="race.pdf",
        content_length=len(content),
        content_type="application/pdf",
        downloaded_at=datetime.now(),
    )
    storage_provider.save_document(document)
    result = storage_provider.get_document(TEST_URL)
    assert result is not None
    assert result.content == content
    assert result.original_filename == "race.pdf"


def test_document_exists(storage_provider) -> None:
    assert not storage_provider.document_exists(TEST_URL)
    content = b"%PDF-1.7"
    document = DownloadedDocument(
        url=TEST_URL,
        content=content,
        original_filename="race.pdf",
        content_length=len(content),
        content_type="application/pdf",
        downloaded_at=datetime.now(),
    )
    storage_provider.save_document(document)
    assert storage_provider.document_exists(TEST_URL)


def test_get_document_returns_none_when_missing(storage_provider) -> None:
    assert storage_provider.get_document(TEST_URL) is None


# ---------------------------------------------------------------------------
# LocalStorageProvider — Documents (implementation-specific tests)
# ---------------------------------------------------------------------------


def test_local_document_path_sharding(local: LocalStorageProvider, tmp_path: Path) -> None:
    content = b"data"
    document = DownloadedDocument(
        url=TEST_URL,
        content=content,
        original_filename="f.pdf",
        content_length=len(content),
        content_type="application/pdf",
        downloaded_at=datetime.now(),
    )
    local.save_document(document)
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
# S3StorageProvider — HTTP cache (implementation-specific tests)
# ---------------------------------------------------------------------------


def test_s3_http_cache_key_sharding(s3_provider: S3StorageProvider) -> None:
    s3_provider.save_http_cache(TEST_URL, "content")
    rid = s3_provider._compute_resource_id(TEST_URL)
    shard = rid[:2]
    expected_key = f"myplugin/cache/http/current/{shard}/{rid}.html"
    assert s3_provider._http_cache_key(TEST_URL) == expected_key


# ---------------------------------------------------------------------------
# S3StorageProvider — Extracted data (implementation-specific tests)
# ---------------------------------------------------------------------------


def test_s3_extracted_key_sharding(s3_provider: S3StorageProvider) -> None:
    rid = s3_provider._compute_resource_id(TEST_URL)
    shard = rid[:2]
    expected_key = f"myplugin/cache/extracted/{shard}/{rid}.json"
    assert s3_provider._extracted_key(TEST_URL) == expected_key


# ---------------------------------------------------------------------------
# S3StorageProvider — Documents (implementation-specific tests)
# ---------------------------------------------------------------------------


def test_s3_document_key_sharding(s3_provider: S3StorageProvider) -> None:
    rid = s3_provider._compute_resource_id(TEST_URL)
    shard = rid[:2]
    expected_prefix = f"myplugin/documents/{shard}/{rid}/"
    assert s3_provider._document_prefix(TEST_URL) == expected_prefix


def test_s3_document_metadata_stored_as_dedicated_object(s3_provider: S3StorageProvider) -> None:
    document = DownloadedDocument(
        url=TEST_URL,
        content=b"content",
        original_filename="race.pdf",
        content_length=100,
        content_type="application/pdf",
        downloaded_at=datetime.now(),
    )
    s3_provider.save_document(document)
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
