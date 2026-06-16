from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from ranking.core.cache import HTTPCacheV1
from ranking.core.httpx_fetcher import httpx_fetcher


class CacheHttpx(HTTPCacheV1):
    """HTTP cache backed by httpx for network fetching."""

    def __init__(
        self,
        plugin_name: str,
        cache_root: Path | str = ".cache",
        normalize_for_comparison: Callable[[str, str], str] | None = None,
    ) -> None:
        """Initialize the cache with httpx as the fetcher."""
        super().__init__(
            plugin_name,
            fetcher=httpx_fetcher,
            cache_root=cache_root,
            normalize_for_comparison=normalize_for_comparison,
        )
