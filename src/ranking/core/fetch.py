from __future__ import annotations

import httpx

HEADERS = {
    "User-Agent": "RankingBot/0.1 (contact: https://github.com/fletort/ranking)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br",
}


def fetch_page(url: str) -> str:
    try:
        response = httpx.get(url, headers=HEADERS, follow_redirects=True)
        response.raise_for_status()
        return response.text
    except httpx.HTTPStatusError as e:
        raise RuntimeError(f"HTTP error {e.response.status_code} for URL: {url}") from e
    except httpx.RequestError as e:
        raise RuntimeError(f"Network error fetching URL: {url}") from e
