from __future__ import annotations

import structlog

from ranking.core.cache import CachePolicy
from ranking.core.cache_httpx import CacheHttpx
from ranking.plugins.breizhchrono.eventdetail import extract_event_detail
from ranking.plugins.breizhchrono.eventlist import EVENTS_LIST_URL, extract_events_list
from ranking.plugins.breizhchrono.plugin import normalize_breizhchrono
from ranking.plugins.breizhchrono.raceresults import extract_race_results
from ranking.plugins.breizhchrono.resultdetail import extract_result_detail

PLUGIN_NAME = "breizhchrono"


def main() -> None:
    log = structlog.get_logger().bind(component="cli")
    cache = CacheHttpx(
        PLUGIN_NAME, normalize_for_comparison=normalize_breizhchrono, save_extracted=True
    )

    try:
        html = cache.fetch(EVENTS_LIST_URL, CachePolicy.REFRESH_AND_CACHE)
    except RuntimeError as exc:
        log.error("fetch_error", error=str(exc))
        return

    events = extract_events_list(html)
    cache.save_extracted_json(EVENTS_LIST_URL, events)
    log.info("extracted_events", count=len(events), events=events)
    if not events:
        return

    first_event_url = "https://resultats.breizhchrono.com/resultats-courses/triathlon-de-la-cote-de-granit-rose-tregastel-2026-1295405190290-19/triathlon-m"
    try:
        event_html = cache.fetch(first_event_url, CachePolicy.CACHE_IF_PRESENT)
    except RuntimeError as exc:
        print(f"Fetch error: {exc}")
        return

    event_detail = extract_event_detail(event_html)
    cache.save_extracted_json(first_event_url, event_detail)
    log.info("extracted_event_detail", event_detail=event_detail)

    if not event_detail or "races" not in event_detail or not event_detail["races"]:
        log.warning("no_event_detail_or_races_found")
        return

    first_race_url = EVENTS_LIST_URL + event_detail["races"][0]["url"]

    try:
        race_html = cache.fetch(first_race_url, CachePolicy.CACHE_IF_PRESENT)
    except RuntimeError as exc:
        log.error("fetch_error", error=str(exc))
        return

    first_race = event_detail["races"][0]
    race_information = {
        "ref_computed": first_race["ref_computed"],
        "heat_computed": first_race["heat_computed"],
    }
    results = extract_race_results(race_html, race_information)
    cache.save_extracted_json(first_race_url, results)
    log.info("extracted_race_results", results=results)

    if not results:
        return

    result_detail_url = results[0].get("result_detail_url_computed")
    if not isinstance(result_detail_url, str) or not result_detail_url:
        log.error("no_computed_result_detail_url_found")
        return

    full_result_detail_url = EVENTS_LIST_URL + result_detail_url
    try:
        detail_html = cache.fetch(full_result_detail_url, CachePolicy.CACHE_IF_PRESENT)
    except RuntimeError as exc:
        log.error("fetch_error", error=str(exc))
        return

    detail = extract_result_detail(detail_html)
    cache.save_extracted_json(full_result_detail_url, detail)
    log.info("extracted_result_detail", result_detail=detail)


if __name__ == "__main__":
    main()
