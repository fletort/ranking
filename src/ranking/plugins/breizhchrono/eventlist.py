from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import TypedDict

EVENTS_LIST_URL = "https://resultats.breizhchrono.com/"


class EventListItem(TypedDict):
    url: str
    name: str
    date_raw: str
    location_raw: str


class _EventListParser(HTMLParser):
    EXPECTED_HEADERS = ["nom de la course", "date", "département"]

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.events: list[EventListItem] = []

        self._in_target_table = False
        self._in_thead = False
        self._in_th = False
        self._in_tr = False
        self._in_td = False
        self._current_headers: list[str] = []
        self._header_valid = False
        self._current_row_url = ""
        self._current_row_cells: list[str] = []
        self._current_cell_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = dict(attrs)

        if tag == "table":
            classes = attrs_dict.get("class", "") or ""
            class_list = set(classes.split())
            required = {"table", "table-bordered", "table-hover"}
            self._in_target_table = required.issubset(class_list)
            return

        if not self._in_target_table:
            return

        if tag == "thead":
            self._in_thead = True
            return

        if tag == "th" and self._in_thead:
            self._in_th = True
            return

        if tag == "tr":
            self._in_tr = True
            self._current_row_cells = []
            self._current_row_url = (
                attrs_dict.get("href", "") or attrs_dict.get("data-href", "") or ""
            )

            if not self._current_row_url:
                onclick = attrs_dict.get("onclick", "") or ""
                match = re.search(r"['\"]([^'\"]+)['\"]", onclick)
                if match:
                    self._current_row_url = match.group(1)
            return

        if tag == "td" and self._in_tr:
            self._in_td = True
            self._current_cell_text = []
            return

        if tag == "a" and self._in_tr and not self._current_row_url:
            self._current_row_url = attrs_dict.get("href", "") or ""

    def handle_endtag(self, tag: str) -> None:
        if tag == "table" and self._in_target_table:
            self._in_target_table = False
            self._in_thead = False
            self._in_th = False
            self._in_tr = False
            self._in_td = False
            return

        if not self._in_target_table:
            return

        if tag == "thead":
            self._in_thead = False
            self._header_valid = (
                self._normalize_headers(self._current_headers) == self.EXPECTED_HEADERS
            )
            return

        if tag == "th" and self._in_th:
            self._in_th = False
            return

        if tag == "td" and self._in_td:
            self._in_td = False
            self._current_row_cells.append("".join(self._current_cell_text).strip())
            return

        if tag == "tr" and self._in_tr:
            self._in_tr = False
            if self._header_valid and len(self._current_row_cells) >= 3:
                name = self._current_row_cells[0]
                if name:
                    self.events.append(
                        {
                            "url": self._current_row_url.strip(),
                            "name": name,
                            "date_raw": self._current_row_cells[1],
                            "location_raw": self._current_row_cells[2],
                        }
                    )
            return

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if not text:
            return

        if self._in_target_table and self._in_th:
            self._current_headers.append(text)
            return

        if self._in_target_table and self._in_td:
            self._current_cell_text.append(text)

    @staticmethod
    def _normalize_headers(headers: list[str]) -> list[str]:
        return [" ".join(header.lower().split()) for header in headers]


def extract_events_list(html_content: str) -> list[EventListItem]:
    try:
        parser = _EventListParser()
        parser.feed(html_content)
        parser.close()
        return parser.events
    except Exception:
        return []
