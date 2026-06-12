from __future__ import annotations

import re
import unicodedata

from bs4 import BeautifulSoup, Tag


def extract_result_detail(html_content: str) -> dict:
    try:
        soup = BeautifulSoup(html_content, "html.parser")
        result: dict[str, str] = {}

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
    if field is None:
        return ""

    title = field.get("title")
    if isinstance(title, str) and ":" in title:
        return title.split(":", 1)[1].strip()
    return field.get_text(" ", strip=True)


def normalize_text(text: str) -> str:
    value = unicodedata.normalize("NFD", text.lower())
    value = "".join(c for c in value if unicodedata.category(c) != "Mn")
    value = re.sub(r"[^a-z0-9]+", "_", value).strip("_")
    return value


def rank_label_to_key(label: str) -> str:
    normalized = normalize_text(label)
    for prefix in ("classement_", "rank_"):
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix) :]

    aliases = {"general": "overall", "categorie": "category", "sexe": "gender"}
    key = aliases.get(normalized, normalized)
    return f"rank_{key}" if key else ""


def extract_rank_value(rank_span: Tag) -> str:
    img = rank_span.find("img")
    if isinstance(img, Tag):
        alt = img.get("alt")
        if isinstance(alt, str) and alt.strip():
            return alt.strip()
    return rank_span.get_text(" ", strip=True)


def extract_time_values(soup: BeautifulSoup) -> dict[str, str]:
    result: dict[str, str] = {}
    for label in soup.select("span.timeTitle"):
        value_tag = label.find_next_sibling("span")
        if not isinstance(value_tag, Tag):
            continue
        add_time_value(result, label.get_text(" ", strip=True), value_tag.get_text(" ", strip=True))

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
    normalized = normalize_text(raw_label)
    if normalized.startswith("temps_"):
        normalized = normalized[len("temps_") :]
    aliases = {"officiel": "official", "reel": "real"}
    key = aliases.get(normalized, normalized)
    if key and raw_value:
        result[f"time_{key}"] = raw_value
