from ranking.plugins.breizhchrono.eventdetail import extract_event_detail


def test_extract_event_detail_returns_event_and_races() -> None:
    html = """
    <html>
      <body>
        <h1>Brest Running Tour 2026 - 10km</h1>
        <div>
          <a class="badge-link" href="https://resultats.breizhchrono.com/event-1/10km">10km</a>
          <a class="badge-link" href="https://resultats.breizhchrono.com/event-1/5km">5km</a>
        </div>
      </body>
    </html>
    """

    result = extract_event_detail(html)

    assert result == {
        "event_race_raw": "Brest Running Tour 2026 - 10km",
        "races": [
            {"url": "https://resultats.breizhchrono.com/event-1/10km", "name": "10km"},
            {"url": "https://resultats.breizhchrono.com/event-1/5km", "name": "5km"},
        ],
    }


def test_extract_event_detail_returns_none_when_no_h1() -> None:
    html = """
    <html>
      <body>
        <div>
          <a class="badge-link" href="https://resultats.breizhchrono.com/event-1/10km">10km</a>
        </div>
      </body>
    </html>
    """

    assert extract_event_detail(html) is None


def test_extract_event_detail_returns_empty_races_when_no_badge_links() -> None:
    html = """
    <html>
      <body>
        <h1>Trail des Monts 2026</h1>
      </body>
    </html>
    """

    result = extract_event_detail(html)

    assert result == {"event_race_raw": "Trail des Monts 2026", "races": []}
