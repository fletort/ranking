from __future__ import annotations

from ranking.core.fetch import fetch_page
from ranking.plugins.breizhchrono.eventdetail import extract_event_detail
from ranking.plugins.breizhchrono.eventlist import EVENTS_LIST_URL, extract_events_list
from ranking.plugins.breizhchrono.raceresults import extract_race_results
from ranking.plugins.breizhchrono.resultdetail import extract_result_detail


def main() -> None:
    try:
        html = fetch_page(EVENTS_LIST_URL)
    except RuntimeError as exc:
        print(f"Fetch error: {exc}")
        return

    events = extract_events_list(html)
    print(f"Extracted {len(events)} events:")
    print(events)
    print("-----------------------------------------------------------------------------")

    if not events:
        return

    first_event_url = "https://resultats.breizhchrono.com/resultats-courses/brest-running-tour-2026-1763690973375-1/10km"
    try:
        event_html = fetch_page(first_event_url)
    except RuntimeError as exc:
        print(f"Fetch error: {exc}")
        return

    event_detail = extract_event_detail(event_html)
    print("Event detail:")
    print(event_detail)
    print("-----------------------------------------------------------------------------")

    if not event_detail or "races" not in event_detail or not event_detail["races"]:
        print("No event detail or races found")
        return

    first_race_url = EVENTS_LIST_URL + event_detail["races"][0]["url"]

    try:
        race_html = fetch_page(first_race_url)
    except RuntimeError as exc:
        print(f"Fetch error: {exc}")
        return

    first_race = event_detail["races"][0]
    race_information = {
        "ref_computed": first_race["ref_computed"],
        "heat_computed": first_race["heat_computed"],
    }
    results = extract_race_results(race_html, race_information)
    print("Race results:")
    print(results)
    print("-----------------------------------------------------------------------------")

    if not results:
        return

    result_detail_url = results[0].get("result_detail_url_computed")
    if not isinstance(result_detail_url, str) or not result_detail_url:
        print("No computed result detail URL found")
        return

    try:
        detail_html = fetch_page(EVENTS_LIST_URL + result_detail_url)
    except RuntimeError as exc:
        print(f"Fetch error: {exc}")
        return

    detail = extract_result_detail(detail_html)
    print("Result detail:")
    print(detail)
    print("-----------------------------------------------------------------------------")


if __name__ == "__main__":
    main()
