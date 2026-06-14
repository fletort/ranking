from __future__ import annotations

from typing import TypedDict

from bs4 import BeautifulSoup


class RaceItem(TypedDict):
    url: str
    name: str
    ref_computed: str
    heat_computed: str


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

            final_url, ref, heat = build_race_url(str(href))

            races.append(
                {
                    "url": final_url,
                    "name": name,
                    "ref_computed": ref,
                    "heat_computed": heat,
                }
            )

        return {"event_race_raw": event_race_raw, "races": races}
    except Exception:
        return None


def build_race_url(raw_url: str) -> tuple[str, str, str]:
    # raw url exemple:
    # /resultats-courses/10h-relais-solidaire-2026-1488071608761-916/10h-relais-solidaire
    # output exemple:
    #   /bc/resultats/course-result.jsp?ref=1488071608761-916&amp;
    #   heat=10h-relais-solidaire&amp;query=&category=&sex=&inter=
    # Returns (url, ref, heat)
    parts = raw_url.strip("/").split("/")

    if len(parts) != 3:
        return raw_url, "", ""  # fallback

    full_slug = parts[-2]
    heat = parts[-1]

    # extraire ref depuis le slug
    # ex: 10h-relais-solidaire-2026-1488071608761-916
    slug_parts = full_slug.split("-")

    if len(slug_parts) < 2:
        return raw_url, "", ""

    ref = "-".join(slug_parts[-2:])  # prend les 2 derniers éléments

    url = f"/bc/resultats/course-result.jsp?ref={ref}&heat={heat}&query=&category=&sex=&inter="
    return url, ref, heat
