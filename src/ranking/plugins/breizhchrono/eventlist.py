from __future__ import annotations

import re
from typing import TypedDict

import structlog
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
        log = structlog.get_logger().bind(
            component="parser",
            entity="event_list",
        )
        soup = BeautifulSoup(html_content, "html.parser")
        table = soup.select_one("div.table-responsive table")
        if table is None:
            log.error("missing_data", type="element", name="table")
            return []

        headers = [
            _normalize_text(th.get_text(" ", strip=True)) for th in table.select("thead > tr > th")
        ]
        if len(headers) < 3 or headers[:3] != EXPECTED_HEADERS:
            log.error(
                "invalid_format",
                type="element",
                name="thead",
                headers=headers,
                headers_expected=EXPECTED_HEADERS,
            )
            return []

        events: list[EventListItem] = []
        for row in table.select("tbody > tr"):
            columns = row.find_all("td")
            if len(columns) < 3:
                log.error(
                    "invalid_format",
                    type="element",
                    name="tr",
                    columns_count=len(columns),
                    columns_expected=3,
                )
                continue

            name = columns[0].get_text(" ", strip=True)
            if not name:
                log.error("missing_data", type="field", name="name")
                continue

            log.debug("extracted_data", type="field", name="name", text=name)
            url = ""
            onclick = _as_text(row.get("onclick"))
            log.debug("extracted_data", type="attribute", name="onclick", text=onclick)
            match = re.search(r"['\"]([^'\"]+)['\"]", onclick)
            if match:
                url = match.group(1).strip()
                log.debug("extracted_data", type="field", name="url", text=url)
            else:
                log.error("invalid_format", type="attribute", name="onclick", text=onclick)

            date_raw = columns[1].get_text(" ", strip=True)
            log.debug("extracted_data", type="field", name="date", text=date_raw)
            location_raw = columns[2].get_text(" ", strip=True)
            log.debug("extracted_data", type="field", name="location", text=location_raw)

            events.append(
                {
                    "url": url,
                    "name": name,
                    "date_raw": date_raw,
                    "location_raw": location_raw,
                }
            )

        return events
    except Exception:
        log.exception("parse_failed")
        return []
