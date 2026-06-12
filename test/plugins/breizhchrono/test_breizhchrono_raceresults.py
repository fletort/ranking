import base64

import pytest
from bs4 import BeautifulSoup

from ranking.plugins.breizhchrono.raceresults import (
    EXPECTED,
    check_decode_order,
    decode_data,
    extract_race_results,
)


def _encode(text: str, key_char: str = "K") -> str:
    key = ord(key_char)
    encoded_bytes = bytes(b ^ key for b in text.encode("utf-8"))
    return base64.b64encode(encoded_bytes).decode("ascii")


def _make_html(encoded_data: str, js_fields: list[str] | None = None) -> str:
    fields_str = ", ".join(js_fields if js_fields is not None else EXPECTED)
    return f"""
    <html>
      <body>
        <script>
          function showResults() {{
            [{fields_str}] = ligne.split("|");
          }}
        </script>
        <div id="data">{encoded_data}</div>
      </body>
    </html>
    """


def _make_row(*values: str) -> str:
    return "|".join(values)


SAMPLE_ROW = _make_row(
    "42", "", "1", "1", "Jean Dupont", "SH", "M", "Club de Brest", "", "00:45:12", "00:45:10", ""
)


# --- decode_data ---


def test_decode_data_round_trip() -> None:
    original = "hello world"
    encoded = _encode(original)
    assert decode_data(encoded) == original


def test_decode_data_with_custom_key() -> None:
    original = "test data"
    encoded = _encode(original, key_char="X")
    assert decode_data(encoded, key_char="X") == original


def test_decode_data_with_pipe_separated_line() -> None:
    line = "42||1|1|Jean Dupont|SH|M|Club de Brest||00:45:12|00:45:10|"
    encoded = _encode(line)
    assert decode_data(encoded) == line


# --- check_decode_order ---


def test_check_decode_order_no_warning_when_fields_match(
    capsys: pytest.CaptureFixture[str],
) -> None:
    html = _make_html(_encode(SAMPLE_ROW))
    soup = BeautifulSoup(html, "html.parser")
    check_decode_order(soup)
    captured = capsys.readouterr()
    assert captured.out == ""


def test_check_decode_order_prints_error_when_no_js_match(
    capsys: pytest.CaptureFixture[str],
) -> None:
    soup = BeautifulSoup("<html><body></body></html>", "html.parser")
    check_decode_order(soup)
    captured = capsys.readouterr()
    assert "[ERROR]" in captured.out


def test_check_decode_order_prints_warn_when_fields_changed(
    capsys: pytest.CaptureFixture[str],
) -> None:
    html = _make_html(_encode(SAMPLE_ROW), js_fields=["nom", "cat", "sexe"])
    soup = BeautifulSoup(html, "html.parser")
    check_decode_order(soup)
    captured = capsys.readouterr()
    assert "[WARN]" in captured.out


# --- extract_race_results ---


def test_extract_race_results_returns_parsed_results() -> None:
    encoded = _encode(SAMPLE_ROW + "\n")
    html = _make_html(encoded)

    results = extract_race_results(html)

    assert len(results) == 1
    assert results[0]["dossard"] == "42"
    assert results[0]["nom"] == "Jean Dupont"
    assert results[0]["officiel"] == "00:45:12"
    assert results[0]["reel"] == "00:45:10"
    assert results[0]["sexe"] == "M"


def test_extract_race_results_returns_all_expected_keys() -> None:
    encoded = _encode(SAMPLE_ROW + "\n")
    html = _make_html(encoded)

    results = extract_race_results(html)

    assert len(results) == 1
    assert list(results[0].keys()) == EXPECTED


def test_extract_race_results_returns_empty_when_no_data_tag() -> None:
    html = "<html><body></body></html>"
    assert extract_race_results(html) == []


def test_extract_race_results_returns_empty_when_data_tag_is_empty() -> None:
    html = '<html><body><div id="data"></div></body></html>'
    assert extract_race_results(html) == []


def test_extract_race_results_skips_lines_with_too_few_parts() -> None:
    short_row = "42|1|1"
    encoded = _encode(short_row + "\n")
    html = _make_html(encoded)
    assert extract_race_results(html) == []


def test_extract_race_results_skips_empty_lines() -> None:
    encoded = _encode("\n\n\n")
    html = _make_html(encoded)
    assert extract_race_results(html) == []


def test_extract_race_results_returns_multiple_rows() -> None:
    row2 = _make_row(
        "99", "", "2", "1", "Marie Martin", "SF", "F", "Brest Athlé", "", "00:50:00", "00:49:58", ""
    )
    encoded = _encode(SAMPLE_ROW + "\n" + row2 + "\n")
    html = _make_html(encoded)

    results = extract_race_results(html)

    assert len(results) == 2
    assert results[0]["nom"] == "Jean Dupont"
    assert results[1]["nom"] == "Marie Martin"
    assert results[1]["sexe"] == "F"
