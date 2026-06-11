from ranking.plugins.breizhchrono.raceresults import extract_race_results


def _make_html(headers: list[str], rows: list[list[str]]) -> str:
    header_html = "".join(f"<th>{h}</th>" for h in headers)
    rows_html = ""
    for row in rows:
        cells = "".join(f"<td>{c}</td>" for c in row)
        rows_html += f"<tr>{cells}</tr>"
    return f"""
    <table class="table">
      <thead><tr>{header_html}</tr></thead>
      <tbody>{rows_html}</tbody>
    </table>
    """


VALID_HEADERS = [
    "Clt",
    "Clt cat",
    "nom categorie",
    "dossard",
    "catégorie",
    "sexe",
    "club/ville",
    "temps officiel",
    "temp réel",
]

SAMPLE_ROW = ["1", "1", "Jean Dupont", "42", "SH", "M", "Club de Brest", "00:45:12", "00:45:10"]


def test_extract_race_results_returns_parsed_results() -> None:
    html = _make_html(VALID_HEADERS, [SAMPLE_ROW])

    results = extract_race_results(html)

    assert results == [
        {
            "rank": "1",
            "rank_category": "1",
            "category_name": "Jean Dupont",
            "bib": "42",
            "category": "SH",
            "gender": "M",
            "club_city": "Club de Brest",
            "official_time": "00:45:12",
            "real_time": "00:45:10",
        }
    ]


def test_extract_race_results_returns_empty_when_no_table() -> None:
    assert extract_race_results("<html><body></body></html>") == []


def test_extract_race_results_returns_empty_when_headers_do_not_match() -> None:
    html = _make_html(["Wrong", "Headers", "Here", "A", "B", "C", "D", "E", "F"], [SAMPLE_ROW])
    assert extract_race_results(html) == []


def test_extract_race_results_skips_rows_with_too_few_columns() -> None:
    html = _make_html(VALID_HEADERS, [["1", "2"]])
    assert extract_race_results(html) == []


def test_extract_race_results_returns_multiple_results() -> None:
    row2 = ["2", "2", "Marie Martin", "99", "SF", "F", "Brest Athlétic", "00:50:00", "00:49:58"]
    html = _make_html(VALID_HEADERS, [SAMPLE_ROW, row2])

    results = extract_race_results(html)

    assert len(results) == 2
    assert results[1]["rank"] == "2"
    assert results[1]["gender"] == "F"
