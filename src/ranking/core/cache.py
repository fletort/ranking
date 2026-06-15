from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Callable
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
    ) -> None:
        """Initialize a cache instance scoped to a plugin name and cache root path."""
        self.plugin_name = plugin_name
        self.fetcher = fetcher
        self.cache_root = Path(cache_root)

    @staticmethod
    def derive_cache_key(url: str) -> str:
        """Derive a deterministic SHA-1 key from a canonicalized full URL string."""
        canonical_url = HTTPCacheV1._canonicalize_url(url)
        return hashlib.sha1(canonical_url.encode("utf-8")).hexdigest()  # noqa: S324

    def fetch(self, url: str, cache_policy: CachePolicy) -> str:
        """Fetch content according to policy and update on-disk cache when needed."""
        if cache_policy is CachePolicy.NO_CACHE:
            return self.fetcher(url)

        current_path = self.current_path(url)

        if cache_policy is CachePolicy.CACHE_IF_PRESENT:
            if current_path.exists():
                return current_path.read_text(encoding="utf-8")

            content = self.fetcher(url)
            self._write_current(current_path, content)
            return content

        existing_content = (
            current_path.read_text(encoding="utf-8") if current_path.exists() else None
        )
        fetched_content = self.fetcher(url)

        if existing_content is not None and existing_content != fetched_content:
            self._write_snapshot(url, fetched_content)

        self._write_current(current_path, fetched_content)
        return fetched_content

    def current_path(self, url: str) -> Path:
        """Return the path of the current cached content file for a URL."""
        key = self.derive_cache_key(url)
        shard = key[:2]
        stem = f"{self._slug_from_url(url)}__{key[:8]}"
        return self.cache_root / self.plugin_name / "http" / "current" / shard / f"{stem}.html"

    def snapshots_dir(self, url: str) -> Path:
        """Return the directory where URL snapshots are stored."""
        key = self.derive_cache_key(url)
        shard = key[:2]
        stem = f"{self._slug_from_url(url)}__{key[:8]}"
        return self.cache_root / self.plugin_name / "http" / "snapshots" / shard / stem

    def _write_current(self, current_path: Path, content: str) -> None:
        """Persist content as the current cache file."""
        current_path.parent.mkdir(parents=True, exist_ok=True)
        current_path.write_text(content, encoding="utf-8")

    def _write_snapshot(self, url: str, content: str) -> None:
        """Persist content as a timestamped snapshot for the URL."""
        snapshots_dir = self.snapshots_dir(url)
        snapshots_dir.mkdir(parents=True, exist_ok=True)
        snapshot_path = snapshots_dir / f"{self._snapshot_timestamp()}.html"
        snapshot_path.write_text(content, encoding="utf-8")

    def _snapshot_timestamp(self) -> str:
        """Return a UTC timestamp formatted for snapshot filenames."""
        return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")

    @staticmethod
    def _slug_from_url(url: str) -> str:
        """Build an informational slug from URL host/path/query for cache filenames."""
        parsed = urlparse(url)
        raw = f"{parsed.netloc}{parsed.path}"
        if parsed.query:
            raw = f"{raw}_{parsed.query}"

        slug = re.sub(r"[^a-zA-Z0-9]+", "_", raw).strip("_").lower()
        return slug or "cached_resource"

    @staticmethod
    def _canonicalize_url(url: str) -> str:
        """Canonicalize URL by sorting query parameters to stabilize cache keys."""
        parsed = urlparse(url)
        sorted_query = sorted(
            parse_qsl(parsed.query, keep_blank_values=True), key=lambda item: item[0]
        )
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
