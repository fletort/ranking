from __future__ import annotations

from typing import TypedDict

from bs4 import BeautifulSoup


class RaceItem(TypedDict):
    url: str
    name: str


class EventDetail(TypedDict):
    event_race_raw: str
    races: list[RaceItem]


def extract_event_detail(html_content: str) -> EventDetail | None:
    try:
        soup = BeautifulSoup(html_content, "html.parser")

        h1 = soup.find("h1")
        if h1 is None:
            return None
        event_race_raw = h1.get_text(" ", strip=True)

        races: list[RaceItem] = []
        for link in soup.select("a.badge-link"):
            href = link.get("href", "")
            name = link.get_text(" ", strip=True)
            if isinstance(href, list):
                href = href[0] if href else ""
            races.append({"url": str(href), "name": name})

        return {"event_race_raw": event_race_raw, "races": races}
    except Exception:
        return None
