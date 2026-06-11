from __future__ import annotations

import unittest

from ranking.plugins.breizhchrono.eventlist import extract_events_list


class TestBreizhChronoEventList(unittest.TestCase):
    def test_extract_events_from_expected_table(self) -> None:
        html = """
        <div class="table-responsive">
            <table class="table table-bordered table-hover">
                <thead>
                    <tr>
                        <th>Nom de la course</th>
                        <th>Date</th>
                        <th>Département</th>
                    </tr>
                </thead>
                <tbody>
                    <tr data-href="/event-1">
                        <td><a href="/event-1">Trail A</a></td>
                        <td>12/10/2026</td>
                        <td>Finistère</td>
                    </tr>
                    <tr onclick="window.location='/event-2'">
                        <td>Trail B</td>
                        <td>13/10/2026 - 14/10/2026</td>
                        <td>Morbihan</td>
                    </tr>
                </tbody>
            </table>
        </div>
        """

        events = extract_events_list(html)

        self.assertEqual(
            events,
            [
                {
                    "url": "/event-1",
                    "name": "Trail A",
                    "date_raw": "12/10/2026",
                    "location_raw": "Finistère",
                },
                {
                    "url": "/event-2",
                    "name": "Trail B",
                    "date_raw": "13/10/2026 - 14/10/2026",
                    "location_raw": "Morbihan",
                },
            ],
        )

    def test_ignore_table_when_headers_do_not_match(self) -> None:
        html = """
        <table class="table table-bordered table-hover">
            <thead>
                <tr>
                    <th>Name</th>
                    <th>Date</th>
                    <th>Department</th>
                </tr>
            </thead>
            <tbody>
                <tr data-href="/event-1">
                    <td>Trail A</td>
                    <td>12/10/2026</td>
                    <td>29</td>
                </tr>
            </tbody>
        </table>
        """

        self.assertEqual(extract_events_list(html), [])


if __name__ == "__main__":
    unittest.main()
