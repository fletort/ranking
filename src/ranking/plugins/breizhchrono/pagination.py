from __future__ import annotations

from bs4 import BeautifulSoup


def _as_text(value: object) -> str:
    if isinstance(value, str):
        return value
    return ""


def extract_next_url(soup: BeautifulSoup) -> str | None:
    next_link = soup.find("a", class_="page-link", string="Suivant")
    if next_link is None:
        return None
    parent_li = next_link.parent
    if parent_li is None:
        return None
    classes = parent_li.get("class")
    if classes is not None and "disabled" in classes:
        return None
    href = _as_text(next_link.get("href"))
    return href if href else None
