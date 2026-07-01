from __future__ import annotations

import re
import unicodedata
from typing import TypedDict

import structlog
from bs4 import BeautifulSoup, Tag


class RankItem(TypedDict):
    """Represents a single global ranking field extracted from a BreizhChrono result detail page.
    Each ranking field has a name, a value (the rank), and an optional total
    (the total number of participants in that ranking).
    """

    name: str
    value: str
    total: str | None


class TimeItem(TypedDict):
    """Represents a single time field extracted from a BreizhChrono result detail page.
    Each time field has a name and a value (the time string).
    """

    name: str
    value: str


class RankTimeItem(TypedDict):
    """Represents a single rank-time field extracted from a BreizhChrono result detail page.
    Each rank-time field has a name, a time value, an overall rank value, and a category
    rank value.
    """

    name: str
    time: str
    overall_rank: str
    category_rank: str


EXPECTED_HEADERS = ["", "temps", "classement", "classement_categorie"]


class ResultDetail(TypedDict):
    """Raw extracted fields from a BreizhChrono runner result detail page."""

    name_bib: str  # The full H1 text as-is (e.g. "CURIE Marie (N°0110)").
    sex: str  # Gets from the identity block, e.g. "Sexe : F" or "Sexe : M".
    # Gets from the identity block, e.g. "Nationalité : FR" or "Nationalité : US".
    nationality: str
    # Gets from the identity block, e.g. "Année de naissance : 1995".
    birth: str
    category: str  # Gets from the identity block, e.g. "Catégorie : SE".
    # Dynamic ranking fields from classement blocks, e.g.
    global_ranks: list[RankItem]
    # "Classement général", "Classement catégorie", "Classement Sexe".
    # Time fields (official, real, …) from the primary time blocks.
    global_times: list[TimeItem]
    # Time fields from other time-ranking blocks.
    other_ranktimes: list[RankTimeItem]


def extract_result_detail(html_content: str) -> ResultDetail | None:
    """Extract raw result detail fields from a BreizhChrono runner detail page.

    Parses the HTML of a per-runner result page and returns an object with the extracted fields.
    The returned object contains only the raw values as they appear on the page,
    without any normalization or transformation.

    Returns None if parsing fails entirely.
    """
    try:
        log = structlog.get_logger().bind(
            component="parser",
            entity="result_detail",
        )
        soup = BeautifulSoup(html_content, "html.parser")
        result: ResultDetail = {
            "name_bib": "",
            "sex": "",
            "nationality": "",
            "birth": "",
            "category": "",
            "global_ranks": [],
            "global_times": [],
            "other_ranktimes": [],
        }

        # Keep the full header text as a single raw field; name and bib number
        # are left together — splitting them is a normalization concern, not extraction.
        h1 = soup.select_one("h1.title")
        if h1:
            result["name_bib"] = h1.get_text(" ", strip=True)
            log.debug("extracted_data", type="element", name="h1.title", text=result["name_bib"])
        else:
            log.warning("missing_data", type="element", name="h1.title")

        identity = soup.find(id="identity")
        log.debug("parse_start", has_identity=bool(identity))
        if isinstance(identity, Tag):
            field_mapping = {
                "sex": "sex",
                "nat": "nationality",
                "birth": "birth",
                "categ": "category",
            }
            for field_id, field_key in field_mapping.items():
                field = identity.find(id=field_id)
                if field:
                    value = extract_identity_value(field)
                    if value:
                        result[field_key] = value  # type: ignore[literal-required]
                        log.debug(
                            "extracted_data",
                            type="field",
                            name=field_key,
                            text=value,
                            location="identity_section",
                        )
                else:
                    log.warning(
                        "missing_data", type="field", name=field_key, location="identity_section"
                    )

        result["global_ranks"] = extract_global_rank_values(soup, log)
        log.debug(
            "extracted_data", type="field", name="global_ranks", count=len(result["global_ranks"])
        )
        result["global_times"] = extract_global_time_values(soup, log)
        log.debug(
            "extracted_data", type="field", name="global_times", count=len(result["global_times"])
        )
        result["other_ranktimes"] = extract_other_ranktime_values(soup, log)
        log.debug(
            "extracted_data",
            type="field",
            name="other_ranktimes",
            count=len(result["other_ranktimes"]),
        )

        log.info(
            "parse_success",
            global_ranks_count=len(result["global_ranks"]),
            global_times_count=len(result["global_times"]),
            other_ranktimes_count=len(result["other_ranktimes"]),
        )
        return result
    except Exception:
        log.exception("parse_failed")
        return None


def extract_identity_value(field: Tag | None) -> str:
    """Extract a single identity field value from its HTML element.

    Prefers the complete ``title`` attribute (e.g. ``title="Sexe : F"``), which carries
    the human-readable value after the colon. Falls back to the element's text
    content if no title is present. Usually, title is always present,
    but this fallback is included for robustness.
    """
    if field is None:
        return ""

    title = field.get("title")
    if isinstance(title, str):
        return title
    return field.get_text(" ", strip=True)


def normalize_text(text: str) -> str:
    """Normalize a label string into a lowercase ASCII snake_case key.

    Strips accents, lowercases, and replaces any run of non-alphanumeric
    characters with underscores, trimming leading/trailing underscores.
    """
    # Decompose characters so accents become separate combining marks
    value = unicodedata.normalize("NFD", text.lower())
    # Drop all combining (accent) characters
    value = "".join(c for c in value if unicodedata.category(c) != "Mn")
    value = re.sub(r"[^a-z0-9]+", "_", value).strip("_")
    return value


def extract_global_rank_values(soup: BeautifulSoup, log: structlog.BoundLogger) -> list[RankItem]:
    """Extract all global ranking fields from the page.
    Each ranking block is rendered as a ``<div class="bloc-classement">`` containing
    a title span (``<span class="classementTitle">``) and a rank index span
    (``<span class="classementIndex">``).
    The rank index span contains an ``<img alt="N"/>`` with the numeric rank value.

    Usually there are three ranking blocks: overall, category, and gender.
    """
    result: list[RankItem] = []
    for bloc in soup.select(".bloc-classement"):
        title_spans = bloc.select("span.classementTitle")
        rank_span = bloc.select_one("span.classementIndex")
        if len(title_spans) < 1 or rank_span is None:
            log.warning("missing_data", type="element", name="classement_block")
            continue

        rank_key = title_spans[0].get_text(" ", strip=True)
        rank_value = extract_rank_value(rank_span)
        # second title span holds the total count, e.g. "/ 2134" → "2134"
        if len(title_spans) > 1:
            total_value = title_spans[1].get_text(" ", strip=True).replace("/", "").strip()

        if rank_key and rank_value:
            new_rank: RankItem = {"name": rank_key, "value": rank_value, "total": None}
            if total_value:
                new_rank["total"] = total_value
            result.append(new_rank)
    return result


def extract_rank_value(rank_span: Tag) -> str:
    """Extract the numeric rank value from a classement index span.

    The rank is rendered as an ``<img alt="N"/>`` inside the span on the live
    site. Falls back to the span's text content for plain-text variants.
    """
    img = rank_span.find("img")
    if isinstance(img, Tag):
        alt = img.get("alt")
        if isinstance(alt, str) and alt.strip():
            return alt.strip()
    return rank_span.get_text(" ", strip=True)


def extract_global_time_values(soup: BeautifulSoup, log: structlog.BoundLogger) -> list[TimeItem]:
    """Extract all time fields from the page.

    Handles two HTML patterns used by BreizhChrono:
    - Primary times: ``<span class="timeTitle">`` followed
    by a sibling ``<span class="timeValue">``.
    - Secondary times: pairs of ``<span class="secondaryTime">`` sharing a parent.

    I think that primary time is always unique and present.
    It seems always to be used for the official time, but I don't know if that is guaranteed.
    Secondary time is optional and unique. It seems to be used for the real time (when defined),
    but I don't know if that is guaranteed.

    The implementation is able to process multiple entries of each type,
    but in practice there is only one of each type on the page.

    Each parent element is processed at most once to avoid duplicate entries.
    """
    result: list[TimeItem] = []
    for label in soup.select("span.timeTitle"):
        value_tag = label.find_next_sibling("span", class_="timeValue")
        if not isinstance(value_tag, Tag):
            log.warning(
                "missing_data",
                type="element",
                name="timeValue",
                label_text=label.get_text(" ", strip=True),
            )
            continue
        key = label.get_text(" ", strip=True)
        value = value_tag.get_text(" ", strip=True)
        new_time: TimeItem = {"name": key, "value": value}
        result.append(new_time)

    # Track already-processed parents to avoid emitting duplicate pairs
    processed_parents: set[int] = set()
    for span in soup.select("span.secondaryTime"):
        parent = span.parent
        if not isinstance(parent, Tag) or id(parent) in processed_parents:
            continue
        pair = parent.find_all("span", class_="secondaryTime", recursive=False)
        if len(pair) >= 2:
            key = pair[0].get_text(" ", strip=True)
            value = pair[1].get_text(" ", strip=True)
            another_time: TimeItem = {"name": key, "value": value}
            result.append(another_time)
            processed_parents.add(id(parent))
        else:
            log.warning(
                "missing_data",
                type="element",
                name="secondaryTime_pair",
                parent_name=parent.name,
                parent_id=parent.get("id"),
            )

    return result


def extract_other_ranktime_values(
    soup: BeautifulSoup, log: structlog.BoundLogger
) -> list[RankTimeItem]:
    """Extract all other rank-time fields from the page.
    These are rendered in a table with four columns: label, time, overall rank, category rank.
    The table is inside a ``<div class="table-responsive">``.
    The Header row is expected to contain the four columns: "", "temps", "classement",
    "classement_categorie".
    The first column is the label.
    The second column is the time value.
    The third column is the overall rank value.
    The fourth column is the category rank value.
    The function returns a list of RankTimeItem dictionaries, each containing the extracted values.
    If the table is not found or the headers do not match the expected values,
    it returns an empty list.
    """
    result: list[RankTimeItem] = []
    table = soup.select_one("div.table-responsive > table")
    if table is None:
        return []

    headers = [
        normalize_text(th.get_text(" ", strip=True)) for th in table.select("thead > tr > th")
    ]
    if len(headers) < len(EXPECTED_HEADERS) or headers[: len(EXPECTED_HEADERS)] != EXPECTED_HEADERS:
        log.warning(
            "invalid_format",
            type="element",
            name="thead",
            headers=headers,
            headers_expected=EXPECTED_HEADERS,
        )
        return []

    for row in table.select("tbody > tr"):
        columns = row.find_all("td")
        if len(columns) < len(EXPECTED_HEADERS):
            log.warning(
                "invalid_format",
                type="element",
                name="tr",
                columns_count=len(columns),
                columns_expected=len(EXPECTED_HEADERS),
                location="ranktime_table",
            )
            continue

        name = columns[0].get_text(" ", strip=True)
        if not name:
            log.warning(
                "missing_data",
                type="field",
                name="name",
                location="ranktime_table",
            )
            continue

        result.append(
            {
                "name": name,
                "time": columns[1].get_text(" ", strip=True),
                "overall_rank": extract_rank_value(columns[2]),
                "category_rank": extract_rank_value(columns[3]),
            }
        )

    return result
