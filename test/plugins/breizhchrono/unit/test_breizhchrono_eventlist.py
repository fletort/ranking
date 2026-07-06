from ranking.plugins.breizhchrono.eventlist import extract_events_list

TABLE_HTML = """
    <div class="table-responsive">
      <table>
        <thead>
          <tr>
            <th>Nom de la course</th>
            <th>Date</th>
            <th>Département</th>
          </tr>
        </thead>
        <tbody>
          <tr onclick="window.location='/event-1';">
            <td>Trail de la Côte</td>
            <td>14/07/2026</td>
            <td>22</td>
          </tr>
        </tbody>
      </table>
    </div>
"""

PAGINATION_FIRST_PAGE = """
    <ul class="pagination justify-content-center flex-wrap">
        <li class="page-item disabled">
            <a class="page-link" href="?page=-1">Précédent</a>
        </li>
        <li class="page-item active">
            <a class="page-link" href="?page=0">1</a>
        </li>
        <li class="page-item ">
            <a class="page-link" href="?page=1">2</a>
        </li>
        <li class="page-item ">
            <a class="page-link" href="?page=1">Suivant</a>
        </li>
    </ul>
"""

PAGINATION_LAST_PAGE = """
    <ul class="pagination justify-content-center flex-wrap">
        <li class="page-item ">
            <a class="page-link" href="?page=60">Précédent</a>
        </li>
        <li class="page-item active">
            <a class="page-link" href="?page=61">62</a>
        </li>
        <li class="page-item disabled">
            <a class="page-link" href="?page=62">Suivant</a>
        </li>
    </ul>
"""


def test_extract_events_list_returns_parsed_events() -> None:
    result = extract_events_list(TABLE_HTML)

    assert result["events"] == [
        {
            "url": "/event-1",
            "name": "Trail de la Côte",
            "date_raw": "14/07/2026",
            "location_raw": "22",
        }
    ]


def test_extract_events_list_returns_empty_when_headers_do_not_match() -> None:
    html = """
    <div class="table-responsive">
      <table>
        <thead>
          <tr>
            <th>Course</th>
            <th>Date</th>
            <th>Lieu</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>Course A</td>
            <td>01/01/2026</td>
            <td>56</td>
          </tr>
        </tbody>
      </table>
    </div>
    """

    result = extract_events_list(html)

    assert result["events"] == []
    assert result["next_url"] is None


def test_extract_events_list_skips_rows_without_event_name() -> None:
    html = """
    <div class="table-responsive">
      <table>
        <thead>
          <tr>
            <th>Nom de la course</th>
            <th>Date</th>
            <th>Département</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td></td>
            <td>01/01/2026</td>
            <td>35</td>
          </tr>
        </tbody>
      </table>
    </div>
    """

    result = extract_events_list(html)

    assert result["events"] == []


def test_extract_events_list_returns_next_url_when_on_first_page() -> None:
    result = extract_events_list(TABLE_HTML + PAGINATION_FIRST_PAGE)

    assert result["next_url"] == "?page=1"


def test_extract_events_list_returns_no_next_url_when_on_last_page() -> None:
    result = extract_events_list(TABLE_HTML + PAGINATION_LAST_PAGE)

    assert result["next_url"] is None


def test_extract_events_list_returns_no_next_url_when_no_pagination() -> None:
    result = extract_events_list(TABLE_HTML)

    assert result["next_url"] is None
