from ranking.plugins.breizhchrono.eventlist import extract_events_list


def test_extract_events_list_returns_parsed_events() -> None:
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
          <tr onclick="window.location='https://resultats.breizhchrono.com/event-1';">
            <td>Trail de la Côte</td>
            <td>14/07/2026</td>
            <td>22</td>
          </tr>
        </tbody>
      </table>
    </div>
    """

    events = extract_events_list(html)

    assert events == [
        {
            "url": "https://resultats.breizhchrono.com/event-1",
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

    assert extract_events_list(html) == []


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

    assert extract_events_list(html) == []
