from __future__ import annotations

from typing import NotRequired, TypedDict

import structlog
from bs4 import BeautifulSoup, Tag


class RaceItem(TypedDict):
    url: str
    name: str
    ref_computed: str
    heat_computed: str


class EventDocument(TypedDict):
    name: str
    url: str


class EventDetail(TypedDict):
    event_race_raw: str
    races: list[RaceItem]
    documents: NotRequired[list[EventDocument]]
    status: NotRequired[str]


def build_event_detail_no_info(status: str) -> EventDetail:
    return {
        "event_race_raw": "",
        "races": [],
        "status": status,
    }


def extract_event_detail(html_content: str) -> EventDetail | None:
    reply: EventDetail | None = None
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

        link_nodes: list[Tag] = []
        divs = soup.select("div.flex-wrap")
        if divs is None or len(divs) == 0:
            log.warning(
                "invalid_format",
                type="element",
                name="div.flex-wrap",
                location="race_list",
                context_text=event_race_raw,
            )
            # try directly a elements (fallback)
            link_nodes = soup.select("a.badge-link")
        else:
            link_nodes = divs[0].select("a.badge-link")

        if len(link_nodes) == 0:
            log.warning(
                "missing_data",
                type="element",
                name="a",
                location="race_list",
                context_text=event_race_raw,
            )

        races: list[RaceItem] = []
        for link in link_nodes:
            href, name = manage_link_node(link, log, "race_list")
            final_url, ref, heat = build_race_url(str(href))
            races.append(
                {
                    "url": final_url,
                    "name": name,
                    "ref_computed": ref,
                    "heat_computed": heat,
                }
            )
        reply = {"event_race_raw": event_race_raw, "races": races}

        other_ranks: list[EventDocument] = []
        if len(divs) > 1:
            log.debug(
                "optional_section_detected",
                type="element",
                name="div.flex-wrap",
                location="event_documents",
                context_text=event_race_raw,
            )
            link_nodes = divs[1].select("a.badge-link")
            if len(link_nodes) == 0:
                log.warning(
                    "missing_data",
                    type="element",
                    name="a",
                    location="event_documents",
                    context_text=event_race_raw,
                )
            else:
                for link in link_nodes:
                    href, name = manage_link_node(link, log, "event_documents")
                    other_ranks.append({"url": href, "name": name})
                    if href is None or not href.lower().endswith(".pdf"):
                        log.warning(
                            "invalid_format",
                            type="element",
                            name="a",
                            href=href,
                            text=name,
                            location="event_documents",
                            reason="expected PDF document link, but found another link",
                        )
                reply["documents"] = other_ranks

        if len(divs) > 2:
            log.warning(
                "unexpected_extra_section",
                type="element",
                name="div.flex-wrap",
                location="event_detail",
                context_text=event_race_raw,
            )

        log.info("parse_success", races_count=len(races))

        return reply
    except Exception:
        log.exception("parse_failed")
        return None


def manage_link_node(link: Tag, log, location: str) -> tuple[str, str]:
    href = link.get("href", "")
    name = link.get_text(" ", strip=True)
    if isinstance(href, list):
        href = href[0] if href else ""

    log.debug("extracted_data", type="element", name="a", href=href, text=name)
    if href is None or href == "":
        href = ""
        log.warning("missing_data", type="field", name="href", location=location)
    if name is None or name == "":
        name = ""
        log.warning("missing_data", type="field", name="text", location=location)

    return href, name


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
