from __future__ import annotations

import os

import httpx

VERIFY_SSL = os.getenv("ENV") != "dev"

HEADERS = {
    "User-Agent": "RankingBot/0.1 (contact: https://github.com/fletort/ranking)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br",
}


def httpx_fetcher(url: str) -> str:
    """Fetch the HTML content of a page at the given URL using httpx.

    Args:
        url: The URL to fetch.

    Returns:
        The raw HTML content as a string.

    Raises:
        RuntimeError: On HTTP error status codes or network-level errors.
    """
    try:
        response = httpx.get(
            url, headers=HEADERS, follow_redirects=True, verify=VERIFY_SSL, timeout=10.0
        )
        response.raise_for_status()
        return response.text
    except httpx.HTTPStatusError as e:
        raise RuntimeError(f"HTTP error {e.response.status_code} for URL: {url}") from e
    except httpx.RequestError as e:
        raise RuntimeError(f"Network error fetching URL: {url}") from e
