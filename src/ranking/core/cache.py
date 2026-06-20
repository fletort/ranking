from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse


class CachePolicy(Enum):
    """Defines v1 cache behavior for each fetch call."""

    NO_CACHE = "NO_CACHE"
    CACHE_IF_PRESENT = "CACHE_IF_PRESENT"
    REFRESH_AND_CACHE = "REFRESH_AND_CACHE"


class HTTPCacheV1:
    """Deterministic, disk-backed HTTP cache with policy-driven reads and writes."""

    def __init__(
        self,
        plugin_name: str,
        fetcher: Callable[[str], str],
        cache_root: Path | str = ".cache",
        normalize_for_comparison: Callable[[str, str], str] | None = None,
        save_extracted: bool = False,
    ) -> None:
        """Initialize a cache instance scoped to a plugin name and cache root path."""
        self.plugin_name = plugin_name
        self.fetcher = fetcher
        self.cache_root = Path(cache_root)
        self.save_extracted = save_extracted

        # Optional normalization hook (plugin-controlled)
        self.normalize_for_comparison = normalize_for_comparison

    @staticmethod
    def derive_cache_key(url: str) -> str:
        """Derive a deterministic SHA-1 key from a canonicalized full URL string."""
        canonical_url = HTTPCacheV1._canonicalize_url(url)
        return hashlib.sha1(canonical_url.encode("utf-8")).hexdigest()  # noqa: S324

    def _has_changed(self, url: str, old: str, new: str) -> bool:
        """Determine if content has changed, optionally using a normalization hook."""
        if self.normalize_for_comparison:
            # Path("old.html").write_text(self.normalize_for_comparison(url, old))
            # Path("new.html").write_text(self.normalize_for_comparison(url, new))
            return self.normalize_for_comparison(url, old) != self.normalize_for_comparison(
                url, new
            )
        return old != new

    def fetch(self, url: str, cache_policy: CachePolicy) -> str:
        """Fetch content according to policy and update on-disk cache when needed."""
        if cache_policy is CachePolicy.NO_CACHE:
            return self.fetcher(url)

        existing_content = None
        current_path = self.current_path(url)
        if current_path.exists():
            existing_content = current_path.read_text(encoding="utf-8")

        if cache_policy is CachePolicy.CACHE_IF_PRESENT:
            if existing_content is not None:
                print(f"[INFO]Cache hit for {url} at {current_path}")
                return existing_content

            content = self.fetcher(url)
            self._write_current(current_path, content)
            return content

        if cache_policy is CachePolicy.REFRESH_AND_CACHE:
            fetched_content = self.fetcher(url)

            if existing_content is None:
                self._write_current(current_path, fetched_content)

            if existing_content is not None and self._has_changed(
                url, existing_content, fetched_content
            ):
                self._write_snapshot(url, existing_content)
                self._write_current(current_path, fetched_content)

            return fetched_content

        return None

    def current_path(self, url: str) -> Path:
        """Return the path of the current cached content file for a URL."""
        key = self.derive_cache_key(url)
        shard = key[:2]
        return self.cache_root / self.plugin_name / "http" / "current" / shard / f"{key}.html"

    def snapshots_dir(self, url: str) -> Path:
        """Return the directory where URL snapshots are stored."""
        key = self.derive_cache_key(url)
        shard = key[:2]
        return self.cache_root / self.plugin_name / "http" / "snapshots" / shard / key

    def extracted_json_path(self, url: str) -> Path:
        """Return the path of the extracted JSON file for a URL."""
        key = self.derive_cache_key(url)
        shard = key[:2]
        return self.cache_root / self.plugin_name / "extracted" / shard / f"{key}.json"

    def save_extracted_json(self, url: str, data: Any) -> None:
        """Persist extracted JSON data to disk if save_extracted is enabled."""
        if not self.save_extracted:
            return
        path = self.extracted_json_path(url)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8", newline="\n"
        )

    def _write_current(self, current_path: Path, content: str) -> None:
        """Persist content as the current cache file."""
        current_path.parent.mkdir(parents=True, exist_ok=True)
        current_path.write_text(content, encoding="utf-8", newline="\n")

    def _write_snapshot(self, url: str, content: str) -> None:
        """Persist content as a timestamped snapshot for the URL."""
        snapshots_dir = self.snapshots_dir(url)
        snapshots_dir.mkdir(parents=True, exist_ok=True)
        snapshot_path = snapshots_dir / f"{self._snapshot_timestamp()}.html"
        snapshot_path.write_text(content, encoding="utf-8", newline="\n")

    def _snapshot_timestamp(self) -> str:
        """Return a UTC timestamp formatted for snapshot filenames."""
        return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H-%M-%S-%f")

    @staticmethod
    def _canonicalize_url(url: str) -> str:
        """Canonicalize URL by sorting query parameters to stabilize cache keys."""
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
