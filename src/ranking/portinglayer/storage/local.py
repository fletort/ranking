from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ranking.core.storage import StorageProvider


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
        return metadata_path.exists()
