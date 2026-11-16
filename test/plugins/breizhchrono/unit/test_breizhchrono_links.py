from __future__ import annotations

import pytest

from ranking.core.url import absolute_url
from ranking.plugins.breizhchrono.eventlist import EVENTS_LIST_URL

SCHEME = "https://"


def _path_part(url: str) -> str:
    return url[len(SCHEME) :]


@pytest.mark.parametrize(
    "href",
    [
        "/resultats-courses/triathlon-la-rincerie/triathlon-s",
        "/bc/resultats/course-result.jsp?ref=1727231492499-3&heat=triathlon-s&query=",
        "/bc/resultats/coureur.jsp?ref=1727231492499-3&heat=triathlon-s&dossard=42",
        "/resultats-courses/triathlon-la-rincerie/triathlon-s/export",
        "/documents?reference=1526881753360-9&name=Classement-par-equipe.pdf",
    ],
)
def test_breizhchrono_hrefs_resolve_to_clean_absolute_urls(href: str) -> None:
    resolved = absolute_url(EVENTS_LIST_URL, href)

    assert resolved == f"{EVENTS_LIST_URL.rstrip('/')}{href}"
    assert resolved.startswith("https://resultats.breizhchrono.com/")
    assert "//" not in _path_part(resolved)


def test_breizhchrono_absolute_document_href_is_kept_unchanged() -> None:
    href = "https://resultats.breizhchrono.com/documents?reference=1&name=x.pdf"

    assert absolute_url(EVENTS_LIST_URL, href) == href
