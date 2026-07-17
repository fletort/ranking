from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import boto3
from botocore.exceptions import ClientError


class StorageProvider(ABC):
    """Abstract base class for URL-based storage operations.

    All storage areas (HTTP cache, snapshots, extracted data, documents) are
    addressed by URL. Path/key construction is an internal detail of each provider.
    """

    def __init__(self, plugin_name: str) -> None:
        """Initialize the storage provider scoped to a plugin name."""
        self.plugin_name = plugin_name

    def _compute_resource_id(self, url: str) -> str:
        """Derive a deterministic SHA-1 resource ID from a canonicalized URL."""
        canonical = self._canonicalize_url(url)
        return hashlib.sha1(canonical.encode("utf-8")).hexdigest()  # noqa: S324

    @staticmethod
    def _canonicalize_url(url: str) -> str:
        """Canonicalize URL by sorting query parameters to stabilize resource IDs."""
        parsed = urlparse(url)
        sorted_query = sorted(parse_qsl(parsed.query, keep_blank_values=True))
        canonical_query = urlencode(sorted_query, doseq=True)
        return urlunparse(
            (
                parsed.scheme,
                parsed.netloc,
                parsed.path,
                parsed.params,
                canonical_query,
                parsed.fragment,
            )
        )

    # --- HTTP cache ---

    @abstractmethod
    def save_http_cache(self, url: str, content: str) -> None:
        """Persist the HTTP response for a URL as the current cached version."""

    @abstractmethod
    def get_http_cache(self, url: str) -> str | None:
        """Return the current cached HTTP response for a URL, or None if absent."""

    @abstractmethod
    def exists_http_cache(self, url: str) -> bool:
        """Return True if a current cached HTTP response exists for the URL."""

    # --- Snapshots ---

    @abstractmethod
    def save_http_snapshot(self, url: str, content: str, timestamp: str) -> None:
        """Persist a timestamped snapshot of an HTTP response for a URL."""

    @abstractmethod
    def list_http_snapshots(self, url: str) -> list[tuple[str, str]]:
        """Return all snapshots for a URL as a list of (timestamp, content) tuples.

        The list is sorted by timestamp in ascending order.
        """

    # --- Extracted data ---

    @abstractmethod
    def save_extracted(self, url: str, data: Any) -> None:
        """Persist extracted JSON data for a URL."""

    @abstractmethod
    def get_extracted(self, url: str) -> Any:
        """Return the extracted JSON data for a URL, or None if absent."""

    # --- Documents ---

    @abstractmethod
    def save_document(self, url: str, content: bytes, metadata: dict[str, Any]) -> None:
        """Persist a downloaded document and its metadata for a URL."""

    @abstractmethod
    def get_document(self, url: str) -> tuple[bytes, dict[str, Any]] | None:
        """Return the (content, metadata) for a downloaded document, or None if absent."""

    @abstractmethod
    def document_exists(self, url: str) -> bool:
        """Return True if a downloaded document exists for the URL."""


class LocalStorageProvider(StorageProvider):
    """StorageProvider backed by the local filesystem.

    Layout::

        <cache_root>/
        └── <plugin_name>/
            ├── http/
            │   ├── current/<shard>/<resource_id>.html
            │   └── snapshots/<shard>/<resource_id>/<timestamp>.html
            └── extracted/<shard>/<resource_id>.json

        <document_root>/
        └── <plugin_name>/<shard>/<resource_id>/
            ├── <original_filename>
            └── metadata.json
    """

    def __init__(
        self,
        plugin_name: str,
        cache_root: Path | str = ".cache",
        document_root: Path | str = ".documents",
    ) -> None:
        """Initialize the local storage provider."""
        super().__init__(plugin_name)
        self.cache_root = Path(cache_root)
        self.document_root = Path(document_root)

    # --- Internal path helpers ---

    def _http_cache_path(self, url: str) -> Path:
        rid = self._compute_resource_id(url)
        shard = rid[:2]
        return self.cache_root / self.plugin_name / "http" / "current" / shard / f"{rid}.html"

    def _snapshots_dir(self, url: str) -> Path:
        rid = self._compute_resource_id(url)
        shard = rid[:2]
        return self.cache_root / self.plugin_name / "http" / "snapshots" / shard / rid

    def _extracted_path(self, url: str) -> Path:
        rid = self._compute_resource_id(url)
        shard = rid[:2]
        return self.cache_root / self.plugin_name / "extracted" / shard / f"{rid}.json"

    def _document_dir(self, url: str) -> Path:
        rid = self._compute_resource_id(url)
        shard = rid[:2]
        return self.document_root / self.plugin_name / shard / rid

    # --- HTTP cache ---

    def save_http_cache(self, url: str, content: str) -> None:
        path = self._http_cache_path(url)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")

    def get_http_cache(self, url: str) -> str | None:
        path = self._http_cache_path(url)
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8")

    def exists_http_cache(self, url: str) -> bool:
        return self._http_cache_path(url).exists()

    # --- Snapshots ---

    def save_http_snapshot(self, url: str, content: str, timestamp: str) -> None:
        snapshots_dir = self._snapshots_dir(url)
        snapshots_dir.mkdir(parents=True, exist_ok=True)
        (snapshots_dir / f"{timestamp}.html").write_text(content, encoding="utf-8", newline="\n")

    def list_http_snapshots(self, url: str) -> list[tuple[str, str]]:
        snapshots_dir = self._snapshots_dir(url)
        if not snapshots_dir.exists():
            return []
        files = sorted(snapshots_dir.glob("*.html"))
        return [(f.stem, f.read_text(encoding="utf-8")) for f in files]

    # --- Extracted data ---

    def save_extracted(self, url: str, data: Any) -> None:
        path = self._extracted_path(url)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8", newline="\n"
        )

    def get_extracted(self, url: str) -> Any:
        path = self._extracted_path(url)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    # --- Documents ---

    def save_document(self, url: str, content: bytes, metadata: dict[str, Any]) -> None:
        doc_dir = self._document_dir(url)
        doc_dir.mkdir(parents=True, exist_ok=True)
        filename = metadata.get("original_filename", "document")
        (doc_dir / filename).write_bytes(content)
        (doc_dir / "metadata.json").write_text(
            json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def get_document(self, url: str) -> tuple[bytes, dict[str, Any]] | None:
        doc_dir = self._document_dir(url)
        metadata_path = doc_dir / "metadata.json"
        if not metadata_path.exists():
            return None
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        filename = metadata.get("original_filename", "document")
        content_path = doc_dir / filename
        if not content_path.exists():
            return None
        return content_path.read_bytes(), metadata

    def document_exists(self, url: str) -> bool:
        doc_dir = self._document_dir(url)
        metadata_path = doc_dir / "metadata.json"
        if not metadata_path.exists():
            return False
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        filename = metadata.get("original_filename", "document")
        return (doc_dir / filename).exists()


class S3StorageProvider(StorageProvider):
    """StorageProvider backed by Amazon S3.

    All objects are stored in a single bucket under plugin-centric prefixes::

        s3://<bucket>/
        └── <plugin_name>/
            ├── cache/
            │   ├── http/
            │   │   ├── current/<shard>/<resource_id>.html
            │   │   └── snapshots/<shard>/<resource_id>/<timestamp>.html
            │   └── extracted/<shard>/<resource_id>.json
            └── documents/<shard>/<resource_id>/
                ├── <original_filename>
                └── metadata.json
    """

    def __init__(
        self,
        plugin_name: str,
        bucket: str,
        region: str | None = None,
    ) -> None:
        """Initialize the S3 storage provider."""
        super().__init__(plugin_name)
        self.bucket = bucket
        self._s3 = boto3.client("s3", region_name=region)

    # --- Internal key helpers ---

    def _http_cache_key(self, url: str) -> str:
        rid = self._compute_resource_id(url)
        shard = rid[:2]
        return f"{self.plugin_name}/cache/http/current/{shard}/{rid}.html"

    def _snapshots_prefix(self, url: str) -> str:
        rid = self._compute_resource_id(url)
        shard = rid[:2]
        return f"{self.plugin_name}/cache/http/snapshots/{shard}/{rid}/"

    def _snapshot_key(self, url: str, timestamp: str) -> str:
        return f"{self._snapshots_prefix(url)}{timestamp}.html"

    def _extracted_key(self, url: str) -> str:
        rid = self._compute_resource_id(url)
        shard = rid[:2]
        return f"{self.plugin_name}/cache/extracted/{shard}/{rid}.json"

    def _document_prefix(self, url: str) -> str:
        rid = self._compute_resource_id(url)
        shard = rid[:2]
        return f"{self.plugin_name}/documents/{shard}/{rid}/"

    def _document_content_key(self, url: str, filename: str) -> str:
        return f"{self._document_prefix(url)}{filename}"

    def _document_metadata_key(self, url: str) -> str:
        return f"{self._document_prefix(url)}metadata.json"

    # --- Internal helpers ---

    def _put(self, key: str, body: bytes, content_type: str = "application/octet-stream") -> None:
        self._s3.put_object(Bucket=self.bucket, Key=key, Body=body, ContentType=content_type)

    def _get(self, key: str) -> bytes | None:
        try:
            response = self._s3.get_object(Bucket=self.bucket, Key=key)
            return response["Body"].read()
        except ClientError as e:
            if e.response["Error"]["Code"] in ("NoSuchKey", "404"):
                return None
            raise

    def _exists(self, key: str) -> bool:
        try:
            self._s3.head_object(Bucket=self.bucket, Key=key)
            return True
        except ClientError as e:
            if e.response["Error"]["Code"] in ("404", "NoSuchKey"):
                return False
            raise

    # --- HTTP cache ---

    def save_http_cache(self, url: str, content: str) -> None:
        self._put(self._http_cache_key(url), content.encode("utf-8"), "text/html")

    def get_http_cache(self, url: str) -> str | None:
        data = self._get(self._http_cache_key(url))
        return data.decode("utf-8") if data is not None else None

    def exists_http_cache(self, url: str) -> bool:
        return self._exists(self._http_cache_key(url))

    # --- Snapshots ---

    def save_http_snapshot(self, url: str, content: str, timestamp: str) -> None:
        self._put(self._snapshot_key(url, timestamp), content.encode("utf-8"), "text/html")

    def list_http_snapshots(self, url: str) -> list[tuple[str, str]]:
        prefix = self._snapshots_prefix(url)
        paginator = self._s3.get_paginator("list_objects_v2")
        keys: list[str] = []
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                if key.endswith(".html"):
                    keys.append(key)
        keys.sort()
        result: list[tuple[str, str]] = []
        for key in keys:
            data = self._get(key)
            if data is not None:
                timestamp = key[len(prefix) :].removesuffix(".html")
                result.append((timestamp, data.decode("utf-8")))
        return result

    # --- Extracted data ---

    def save_extracted(self, url: str, data: Any) -> None:
        body = json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8")
        self._put(self._extracted_key(url), body, "application/json")

    def get_extracted(self, url: str) -> Any:
        data = self._get(self._extracted_key(url))
        return json.loads(data.decode("utf-8")) if data is not None else None

    # --- Documents ---

    def save_document(self, url: str, content: bytes, metadata: dict[str, Any]) -> None:
        filename = metadata.get("original_filename", "document")
        content_type = metadata.get("content_type", "application/octet-stream")
        self._put(self._document_content_key(url, filename), content, content_type)
        metadata_body = json.dumps(metadata, indent=2, ensure_ascii=False).encode("utf-8")
        self._put(self._document_metadata_key(url), metadata_body, "application/json")

    def get_document(self, url: str) -> tuple[bytes, dict[str, Any]] | None:
        metadata_data = self._get(self._document_metadata_key(url))
        if metadata_data is None:
            return None
        metadata = json.loads(metadata_data.decode("utf-8"))
        filename = metadata.get("original_filename", "document")
        content = self._get(self._document_content_key(url, filename))
        if content is None:
            return None
        return content, metadata

    def document_exists(self, url: str) -> bool:
        return self._exists(self._document_metadata_key(url))
