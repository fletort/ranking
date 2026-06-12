from __future__ import annotations

import re
import unicodedata

from bs4 import BeautifulSoup, Tag


def extract_result_detail(html_content: str) -> dict:
    """Extract raw result detail fields from a BreizhChrono runner detail page.

    Parses the HTML of a per-runner result page and returns a flat dictionary of
    raw extracted fields:
    - ``header_raw``: the full H1 text as-is (e.g. ``"CURIE Marie (N°0110)"``).
    - ``sex``, ``nationality``, ``birth``, ``category``: identity block fields.
    - ``rank_*`` / ``rank_*_total``: dynamic ranking fields from classement blocks.
    - ``time_*``: time fields (official, real, …).

    Returns an empty dict if parsing fails entirely.
    """
    try:
        soup = BeautifulSoup(html_content, "html.parser")
        result: dict[str, str] = {}

        # Keep the full header text as a single raw field; name and bib number
        # are left together — splitting them is a normalization concern, not extraction.
        h1 = soup.select_one("h1.title")
        if h1:
            result["header_raw"] = h1.get_text(" ", strip=True)

        identity = soup.find(id="identity")
        if isinstance(identity, Tag):
            for field_id, field_key in (
                ("sex", "sex"),
                ("nat", "nationality"),
                ("birth", "birth"),
                ("categ", "category"),
            ):
                field = identity.find(id=field_id)
                value = extract_identity_value(field)
                if value:
                    result[field_key] = value

        for bloc in soup.select(".bloc-classement"):
            title_spans = bloc.select("span.classementTitle")
            rank_span = bloc.select_one("span.classementIndex")
            if len(title_spans) < 2 or rank_span is None:
                continue

            raw_title = title_spans[0].get_text(" ", strip=True)
            rank_key = rank_label_to_key(raw_title)
            rank_value = extract_rank_value(rank_span)
            # second title span holds the total count, e.g. "/ 2134" → "2134"
            total_value = title_spans[1].get_text(" ", strip=True).replace("/", "").strip()

            if rank_key and rank_value:
                result[f"{rank_key}"] = rank_value
            if rank_key and total_value:
                result[f"{rank_key}_total"] = total_value

        result.update(extract_time_values(soup))
        return result
    except Exception:
        return {}


def extract_identity_value(field: Tag | None) -> str:
    """Extract a single identity field value from its HTML element.

    Prefers the ``title`` attribute (e.g. ``title="Sexe : F"``), which carries
    the human-readable value after the colon. Falls back to the element's text
    content when no colon-delimited title is present.
    """
    if field is None:
        return ""

    title = field.get("title")
    if isinstance(title, str) and ":" in title:
        return title.split(":", 1)[1].strip()
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


def rank_label_to_key(label: str) -> str:
    """Convert a classement block title into a normalized ``rank_*`` key.

    Strips common French prefixes (``classement_``, ``rank_``) and applies
    alias translations (e.g. ``general`` → ``overall``, ``sexe`` → ``gender``)
    so that output keys are stable and language-independent.

    Returns an empty string when the label cannot be turned into a valid key.
    """
    normalized = normalize_text(label)
    # Strip any leading "classement_" or "rank_" prefix already baked into the label
    for prefix in ("classement_", "rank_"):
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix) :]

    aliases = {"general": "overall", "categorie": "category", "sexe": "gender"}
    key = aliases.get(normalized, normalized)
    return f"rank_{key}" if key else ""


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


def extract_time_values(soup: BeautifulSoup) -> dict[str, str]:
    """Extract all time fields from the page.

    Handles two HTML patterns used by BreizhChrono:
    - Primary times: ``<span class="timeTitle">`` followed by a sibling ``<span>``.
    - Secondary times: pairs of ``<span class="secondaryTime">`` sharing a parent.

    Each parent element is processed at most once to avoid duplicate entries.
    """
    result: dict[str, str] = {}
    for label in soup.select("span.timeTitle"):
        value_tag = label.find_next_sibling("span")
        if not isinstance(value_tag, Tag):
            continue
        add_time_value(result, label.get_text(" ", strip=True), value_tag.get_text(" ", strip=True))

    # Track already-processed parents to avoid emitting duplicate pairs
    processed_parents: set[int] = set()
    for span in soup.select("span.secondaryTime"):
        parent = span.parent
        if not isinstance(parent, Tag) or id(parent) in processed_parents:
            continue
        pair = parent.find_all("span", class_="secondaryTime", recursive=False)
        if len(pair) >= 2:
            add_time_value(
                result, pair[0].get_text(" ", strip=True), pair[1].get_text(" ", strip=True)
            )
            processed_parents.add(id(parent))

    return result


def add_time_value(result: dict[str, str], raw_label: str, raw_value: str) -> None:
    """Normalize a time label and insert the corresponding value into *result*.

    Strips the French ``temps_`` prefix and applies alias translations
    (e.g. ``officiel`` → ``official``, ``reel`` → ``real``) so keys are
    stable and language-independent. Entries with an empty value are skipped.
    """
    normalized = normalize_text(raw_label)
    if normalized.startswith("temps_"):
        normalized = normalized[len("temps_") :]
    aliases = {"officiel": "official", "reel": "real"}
    key = aliases.get(normalized, normalized)
    if key and raw_value:
        result[f"time_{key}"] = raw_value
