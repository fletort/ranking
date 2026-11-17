import pytest
from structlog.testing import capture_logs

from ranking.plugins.breizhchrono.eventdetail import build_race_url, extract_event_detail


def test_build_race_url_return_correct_url() -> None:
    raw_url = "/resultats-courses/10h-relais-solidaire-2026-1488071608761-916/10h-relais-solidaire"
    url, ref, heat = build_race_url(raw_url)
    assert (
        url == "/bc/resultats/course-result.jsp?ref=1488071608761-916&heat=10h-relais-"
        "solidaire&query=&category=&sex=&inter="
    )
    assert ref == "1488071608761-916"
    assert heat == "10h-relais-solidaire"


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
                "source_url": "/resultats-course/10km-2026-12345-123/10km",
                "technical_url": "/bc/resultats/course-result.jsp?ref=12345-123&heat=10km"
                "&query=&category=&sex=&inter=",
                "name": "10km",
                "ref_computed": "12345-123",
                "heat_computed": "10km",
            },
            {
                "source_url": "/resultats-course/5km-2026-678912334-222/5km",
                "technical_url": "/bc/resultats/course-result.jsp?ref=678912334-222&heat=5km"
                "&query=&category=&sex=&inter=",
                "name": "5km",
                "ref_computed": "678912334-222",
                "heat_computed": "5km",
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


def test_extract_event_detail_warns_and_skips_non_document_link() -> None:
    html = """
    <html>
      <body>
        <h1>Challenge My Data Run</h1>
        <div class="flex-wrap">
          <a class="badge-link" href="/resultats-course/10km-2026-12345-123/10km">10km</a>
        </div>
        <div class="flex-wrap">
          <a class="badge-link" href="/bc/ekiden/?e=123">Resultats Ekiden</a>
        </div>
      </body>
    </html>
    """

    with capture_logs() as logs:
        result = extract_event_detail(html)

    assert result is not None
    # The web link is filtered out: it is never queued, so the CLI never downloads it.
    assert result["documents"] == []

    warnings = [event for event in logs if event["event"] == "invalid_format"]
    assert len(warnings) == 1
    assert warnings[0]["location"] == "event_documents"
    # The warning carries the resolved absolute URL.
    assert warnings[0]["href"] == "https://resultats.breizhchrono.com/bc/ekiden/?e=123"


@pytest.mark.parametrize("ext", [".pdf", ".csv", ".xls", ".xlsx"])
def test_extract_event_detail_keeps_allowed_document_extensions(ext: str) -> None:
    html = f"""
    <html>
      <body>
        <h1>Event</h1>
        <div class="flex-wrap">
          <a class="badge-link" href="/resultats-course/race-2026-1-1/heat">Heat</a>
        </div>
        <div class="flex-wrap">
          <a class="badge-link" href="/documents?name=ranking{ext}">Document</a>
        </div>
      </body>
    </html>
    """

    with capture_logs() as logs:
        result = extract_event_detail(html)

    assert result is not None
    assert result["documents"] == [{"url": f"/documents?name=ranking{ext}", "name": "Document"}]
    assert [event for event in logs if event["event"] == "invalid_format"] == []
