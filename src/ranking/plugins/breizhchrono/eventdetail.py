from __future__ import annotations

from typing import TypedDict

import structlog
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
        log = structlog.get_logger().bind(
            component="parser",
            entity="event_detail",
        )

        soup = BeautifulSoup(html_content, "html.parser")

        h1 = soup.find("h1")
        if h1 is None:
            log.error("missing_data", type="element", name="h1")
            return None
        event_race_raw = h1.get_text(" ", strip=True)
        log.debug("extracted_data", type="element", name="h1", text=event_race_raw)

        races: list[RaceItem] = []
        for link in soup.select("a.badge-link"):
            href = link.get("href", "")
            name = link.get_text(" ", strip=True)
            if isinstance(href, list):
                href = href[0] if href else ""

            log.debug("extracted_data", type="element", name="a", href=href, text=name)
            if href == "":
                log.warning("missing_data", type="field", name="href", location="race_list")
            if name == "":
                log.warning("missing_data", type="field", name="text", location="race_list")

            final_url, ref, heat = build_race_url(str(href))
            races.append(
                {
                    "url": final_url,
                    "name": name,
                    "ref_computed": ref,
                    "heat_computed": heat,
                }
            )

        if len(races) == 0:
            log.warning(
                "missing_data",
                type="element",
                name="a",
                location="race_list",
                context_text=event_race_raw,
            )

        log.info("parse_success", races_count=len(races))

        return {"event_race_raw": event_race_raw, "races": races}
    except Exception:
        log.exception("parse_failed")
        return None


def build_race_url(raw_url: str) -> tuple[str, str, str]:
    # raw url exemple:
    # /resultats-courses/10h-relais-solidaire-2026-1488071608761-916/10h-relais-solidaire
    # output exemple:
    #   /bc/resultats/course-result.jsp?ref=1488071608761-916&amp;
    #   heat=10h-relais-solidaire&amp;query=&category=&sex=&inter=
    # Returns (url, ref, heat)
    log = structlog.get_logger()
    parts = raw_url.strip("/").split("/")

    if len(parts) != 3:
        log.error("Unexpected URL format, expected 3 parts between slashes", raw_url=raw_url)
        return raw_url, "", ""  # fallback

    full_slug = parts[-2]
    heat = parts[-1]

    # extraire ref depuis le slug
    # ex: 10h-relais-solidaire-2026-1488071608761-916
    slug_parts = full_slug.split("-")

    if len(slug_parts) < 2:
        log.error(
            "Unexpected slug format, expected at least 2 parts between dashes", full_slug=full_slug
        )
        return raw_url, "", ""

    ref = "-".join(slug_parts[-2:])  # prend les 2 derniers éléments

    url = f"/bc/resultats/course-result.jsp?ref={ref}&heat={heat}&query=&category=&sex=&inter="
    log.debug("Built race URL", url=url, ref=ref, heat=heat)
    return url, ref, heat
