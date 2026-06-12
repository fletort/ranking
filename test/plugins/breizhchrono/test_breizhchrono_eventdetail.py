from ranking.plugins.breizhchrono.eventdetail import build_race_url, extract_event_detail


def test_build_race_url_return_correct_url() -> None:
    raw_url = "/resultats-courses/10h-relais-solidaire-2026-1488071608761-916/10h-relais-solidaire"
    output = build_race_url(raw_url)
    assert (
        output == "/bc/resultats/course-result.jsp?ref=1488071608761-916&heat=10h-relais-"
        "solidaire&query=&category=&sex=&inter="
    )


def test_extract_event_detail_returns_event_and_races() -> None:
    html = """
    <html>
      <body>
        <h1>Brest Running Tour 2026 - 10km</h1>
        <div>
          <a class="badge-link" href="/resultats-course/10km-2026-12345-123/10km">10km</a>
          <a class="badge-link" href="/resultats-course/5km-2026-678912334-222/5km">5km</a>
        </div>
      </body>
    </html>
    """

    result = extract_event_detail(html)

    assert result == {
        "event_race_raw": "Brest Running Tour 2026 - 10km",
        "races": [
            {
                "url": "/bc/resultats/course-result.jsp?ref=12345-123&heat=10km"
                "&query=&category=&sex=&inter=",
                "name": "10km",
            },
            {
                "url": "/bc/resultats/course-result.jsp?ref=678912334-222&heat=5km"
                "&query=&category=&sex=&inter=",
                "name": "5km",
            },
        ],
    }


def test_extract_event_detail_returns_none_when_no_h1() -> None:
    html = """
    <html>
      <body>
        <div>
          <a class="badge-link" href="/resultats-course/10km-2026-12345-123/10km">10km</a>
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
