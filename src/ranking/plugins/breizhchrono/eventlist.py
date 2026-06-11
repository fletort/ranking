from __future__ import annotations

import re
from typing import TypedDict

from bs4 import BeautifulSoup

EVENTS_LIST_URL = "https://resultats.breizhchrono.com/"


class EventListItem(TypedDict):
    url: str
    name: str
    date_raw: str
    location_raw: str


EXPECTED_HEADERS = ["nom de la course", "date", "département"]


def _normalize_text(value: str) -> str:
    return " ".join(value.lower().split())


def _as_text(value: object) -> str:
    if isinstance(value, str):
        return value
    return ""


def extract_events_list(html_content: str) -> list[EventListItem]:
    try:
        soup = BeautifulSoup(html_content, "html.parser")
        table = soup.select_one("div.table-responsive table.table.table-bordered.table-hover")
        if table is None:
            table = soup.select_one("table.table.table-bordered.table-hover")
        if table is None:
            return []

        headers = [_normalize_text(th.get_text(" ", strip=True)) for th in table.select("thead th")]
        if len(headers) < 3 or headers[:3] != EXPECTED_HEADERS:
            return []

        events: list[EventListItem] = []
        for row in table.select("tbody tr"):
            columns = row.find_all("td")
            if len(columns) < 3:
                continue

            name = columns[0].get_text(" ", strip=True)
            if not name:
                continue

            url = ""
            link = columns[0].find("a", href=True)
            if link is not None:
                url = _as_text(link.get("href")).strip()
            if not url:
                url = _as_text(row.get("data-href")).strip()
            if not url:
                onclick = _as_text(row.get("onclick"))
                match = re.search(r"['\"]([^'\"]+)['\"]", onclick)
                if match:
                    url = match.group(1).strip()

            events.append(
                {
                    "url": url,
                    "name": name,
                    "date_raw": columns[1].get_text(" ", strip=True),
                    "location_raw": columns[2].get_text(" ", strip=True),
                }
            )

        return events
    except Exception:
        return []
