from __future__ import annotations

from typing import TypedDict

from bs4 import BeautifulSoup


class RaceResultItem(TypedDict):
    rank: str
    rank_category: str
    category_name: str
    bib: str
    category: str
    gender: str
    club_city: str
    official_time: str
    real_time: str


EXPECTED_HEADERS = [
    "clt",
    "clt cat",
    "nom categorie",
    "dossard",
    "catégorie",
    "sexe",
    "club/ville",
    "temps officiel",
    "temp réel",
]


def _normalize_text(value: str) -> str:
    return " ".join(value.lower().split())


def extract_race_results(html_content: str) -> list[RaceResultItem]:
    try:
        soup = BeautifulSoup(html_content, "html.parser")
        table = soup.select_one("table.table")
        if table is None:
            return []

        headers = [
            _normalize_text(th.get_text(" ", strip=True)) for th in table.select("thead > tr > th")
        ]
        expected_count = len(EXPECTED_HEADERS)
        if len(headers) < expected_count or headers[:expected_count] != EXPECTED_HEADERS:
            return []

        results: list[RaceResultItem] = []
        for row in table.select("tbody > tr"):
            columns = row.find_all("td")
            if len(columns) < len(EXPECTED_HEADERS):
                continue

            results.append(
                {
                    "rank": columns[0].get_text(" ", strip=True),
                    "rank_category": columns[1].get_text(" ", strip=True),
                    "category_name": columns[2].get_text(" ", strip=True),
                    "bib": columns[3].get_text(" ", strip=True),
                    "category": columns[4].get_text(" ", strip=True),
                    "gender": columns[5].get_text(" ", strip=True),
                    "club_city": columns[6].get_text(" ", strip=True),
                    "official_time": columns[7].get_text(" ", strip=True),
                    "real_time": columns[8].get_text(" ", strip=True),
                }
            )

        return results
    except Exception:
        return []
