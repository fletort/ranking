from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any

import boto3
from botocore.exceptions import ClientError

from ranking.core.storage.provider import DownloadedDocument, HealthCheckResult, StorageProvider


class S3StorageProvider(StorageProvider):
    """StorageProvider backed by S3-compatible object storage.

    Common S3 storage behavior is implemented here, while provider-specific implementations
    can extend this class to customize boto3 client configuration through the
    `_build_client_kwargs()` extension hook.

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
        endpoint_url: str | None = None,
        access_key_id: str | None = None,
        secret_access_key: str | None = None,
    ) -> None:
        """Initialize the S3 storage provider."""
        super().__init__(plugin_name)
        self.bucket = bucket
        self.region = region
        self.endpoint_url = endpoint_url
        self.access_key_id = access_key_id
        self.secret_access_key = secret_access_key
        self._s3 = boto3.client(service_name="s3", **self._build_client_kwargs())

    def _build_client_kwargs(self) -> dict[str, Any]:
        """Build generic keyword arguments for the boto3 S3 client."""
        kwargs = {}
        if self.region:
            kwargs["region_name"] = self.region

        if self.endpoint_url:
            kwargs["endpoint_url"] = self.endpoint_url

        if self.access_key_id:
            kwargs["aws_access_key_id"] = self.access_key_id

        if self.secret_access_key:
            kwargs["aws_secret_access_key"] = self.secret_access_key

        return kwargs

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

    def save_document(self, document: DownloadedDocument) -> None:
        filename = document.original_filename if document.original_filename else "document"
        content_type = document.content_type if document.content_type else ""
        self._put(
            self._document_content_key(document.url, filename),
            document.content,
            content_type,
        )
        metadata = {
            "key": self._compute_resource_id(document.url),
            "url": document.url,
            "original_filename": filename,
            "content_type": content_type,
            "content_length": document.content_length,
            "downloaded_at": document.downloaded_at.isoformat(),
        }
        metadata_body = json.dumps(metadata, indent=2, ensure_ascii=False).encode("utf-8")
        self._put(self._document_metadata_key(document.url), metadata_body, "application/json")

    def get_document(self, url: str) -> DownloadedDocument | None:
        metadata_data = self._get(self._document_metadata_key(url))
        if metadata_data is None:
            return None
        metadata = json.loads(metadata_data.decode("utf-8"))
        filename = metadata.get("original_filename", "document")
        content = self._get(self._document_content_key(url, filename))
        if content is None:
            return None
        return DownloadedDocument(
            url=url,
            content=content,
            original_filename=metadata.get("original_filename"),
            content_type=metadata.get("content_type"),
            content_length=metadata.get("content_length"),
            downloaded_at=datetime.fromisoformat(metadata.get("downloaded_at")),
        )

    def document_exists(self, url: str) -> bool:
        return self._exists(self._document_metadata_key(url))

    def healthcheck(self) -> HealthCheckResult:
        checks: dict[str, bool] = {}
        details: dict[str, str] = {}

        details["bucket"] = self.bucket
        if self.region:
            details["region"] = self.region
        if self.endpoint_url:
            details["endpoint_url"] = self.endpoint_url

        # bucket existence
        try:
            self._s3.head_bucket(Bucket=self.bucket)
            checks["bucket_access"] = True

        except ClientError:
            checks["bucket_access"] = False

        # write/read/delete
        object_key = f"{self.plugin_name}/healthcheck/{uuid.uuid4()}.txt"

        try:
            self._s3.put_object(
                Bucket=self.bucket,
                Key=object_key,
                Body=b"healthcheck",
            )
            checks["write"] = True
        except Exception:
            checks["write"] = False

        try:
            response = self._s3.get_object(
                Bucket=self.bucket,
                Key=object_key,
            )

            content = response["Body"].read()
            checks["read"] = content == b"healthcheck"

        except Exception:
            checks["read"] = False

        try:
            self._s3.delete_object(
                Bucket=self.bucket,
                Key=object_key,
            )
            checks["delete"] = True

        except Exception:
            checks["delete"] = False

        success = all(checks.values())

        return HealthCheckResult(
            backend="s3",
            success=success,
            checks=checks,
            details=details,
        )
