from __future__ import annotations

import base64
import re
from collections.abc import Mapping
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup

EXPECTED = [
    "dossard",
    "diploma",
    "classement",
    "classementCat",
    "nom",
    "cat",
    "sexe",
    "club",
    "inter",
    "officiel",
    "reel",
    "endurance",
]


def decode_data(encoded: str, key_char: str = "K") -> str:
    """
    Decode a base64-encoded string using a simple XOR cipher with the given key character.
    Do as the official JavaScript does (see showResults function in the page source).
    Args:
        encoded: The base64-encoded string to decode.
        key_char: A single character used as the key for the XOR cipher (default is 'K').
    Returns:    The decoded string.
    """

    raw = base64.b64decode(encoded)
    key = ord(key_char)
    decoded_bytes = bytes(b ^ key for b in raw)
    return decoded_bytes.decode("utf-8")


def check_decode_order(soup: BeautifulSoup) -> None:
    """Check the order of fields used in the JavaScript decoding logic.
    This is a sanity check to detect if the website has changed its encoding logic.
    It looks for the JavaScript code that does the decoding and extracts the order of fields.
    If the order does not match the expected one, it prints a warning.
    Args:
        soup: The BeautifulSoup object of the page, used to find the relevant JavaScript code.
    """

    scripts = soup.find_all("script")
    js_code = "\n".join(s.get_text() for s in scripts if s.get_text())
    match = re.search(r"\[\s*([^\]]+?)\s*\]\s*=\s*ligne\.split", js_code, re.DOTALL)

    if not match:
        print("[ERROR] No destructuring found")
    else:
        fields = [f.strip() for f in match.group(1).split(",")]

        if fields != EXPECTED:
            print("[WARN] Field mapping changed:", fields)


def extract_race_results(
    html: str, race_information: Mapping[str, str] | None = None
) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    check_decode_order(soup)
    ref, heat = extract_ref_and_heat(race_information)

    data_tag = soup.find(id="data")
    if not data_tag:
        return []

    encoded = data_tag.get_text(strip=True)

    decoded = decode_data(encoded)

    results = []

    for line in decoded.split("\n"):
        if not line.strip():
            continue

        parts = line.split("|")

        if len(parts) < len(EXPECTED):
            continue  # sécurité

        result = {key: parts[i] if i < len(parts) else None for i, key in enumerate(EXPECTED)}

        dossard = result.get("dossard")
        if isinstance(dossard, str) and dossard and ref and heat:
            result["result_detail_url_computed"] = (
                f"/bc/resultats/coureur.jsp?ref={ref}&heat={heat}&dossard={dossard}"
            )

        results.append(result)

    return results


def extract_ref_and_heat(race_information: Mapping[str, str] | None) -> tuple[str, str]:
    if not race_information:
        return "", ""

    ref = race_information.get("ref_computed")
    heat = race_information.get("heat_computed")

    if isinstance(ref, str) and isinstance(heat, str) and ref and heat:
        return ref, heat

    race_url = race_information.get("url")
    if not isinstance(race_url, str):
        return "", ""

    parsed = urlparse(race_url)
    params = parse_qs(parsed.query)
    return params.get("ref", [""])[0], params.get("heat", [""])[0]
