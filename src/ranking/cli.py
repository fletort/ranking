from __future__ import annotations

from ranking.core.fetch import fetch_page
from ranking.plugins.breizhchrono.eventlist import EVENTS_LIST_URL, extract_events_list


def main() -> None:
    try:
        html = fetch_page(EVENTS_LIST_URL)
    except RuntimeError as exc:
        print(f"Fetch error: {exc}")
        return

    events = extract_events_list(html)
    print(events)


if __name__ == "__main__":
    main()
