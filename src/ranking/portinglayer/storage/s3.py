from __future__ import annotations

import json
from typing import Any

import boto3
from botocore.exceptions import ClientError

from ranking.core.storage import StorageProvider


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

    def save_http_cache(self, url: str, content: str) -> None:
        self._put(self._http_cache_key(url), content.encode("utf-8"), "text/html")

    def get_http_cache(self, url: str) -> str | None:
        data = self._get(self._http_cache_key(url))
        return data.decode("utf-8") if data is not None else None

    def exists_http_cache(self, url: str) -> bool:
        return self._exists(self._http_cache_key(url))

    def save_http_snapshot(self, url: str, content: str, timestamp: str) -> None:
        self._put(self._snapshot_key(url, timestamp), content.encode("utf-8"), "text/html")

    def list_http_snapshots(self, url: str) -> list[tuple[str, str]]:
        """Fetch all snapshots for a URL.

        This performs one S3 listing plus one S3 GET request per snapshot and is
        intended for small histories.
        """
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

    def save_extracted(self, url: str, data: Any) -> None:
        body = json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8")
        self._put(self._extracted_key(url), body, "application/json")

    def get_extracted(self, url: str) -> Any:
        data = self._get(self._extracted_key(url))
        return json.loads(data.decode("utf-8")) if data is not None else None

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
