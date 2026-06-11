from __future__ import annotations

from ranking.core.fetch import fetch_page
from ranking.plugins.breizhchrono.eventlist import EVENTS_LIST_URL, extract_events_list
from ranking.plugins.breizhchrono.raceresults import extract_race_results


def main() -> None:
    try:
        html = fetch_page(EVENTS_LIST_URL)
    except RuntimeError as exc:
        print(f"Fetch error: {exc}")
        return

    events = extract_events_list(html)
    print(events)

    if not events:
        print("No events found.")
        return

    first_url = events[0]["url"]
    if not first_url:
        print("First event has no URL.")
        return

    try:
        race_html = fetch_page(first_url)
    except RuntimeError as exc:
        print(f"Fetch error: {exc}")
        return

    results = extract_race_results(race_html)
    print(results)


if __name__ == "__main__":
    main()
