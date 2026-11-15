from __future__ import annotations

import pytest

from ranking.core.url import (
    SUPPORTED_HTTP_SCHEMES,
    absolute_url,
    canonicalize_url,
    validate_http_scheme,
)

BASE = "https://resultats.breizhchrono.com/"


# --- absolute_url: generic link resolution (the plugin only supplies the base URL) ---


def test_absolute_url_resolves_a_root_relative_href() -> None:
    assert absolute_url(BASE, "/resultats-courses/x") == (
        "https://resultats.breizhchrono.com/resultats-courses/x"
    )


def test_absolute_url_does_not_duplicate_the_separator() -> None:
    """Regression: ``BASE + href`` used to produce ``https://host//resultats-courses/...``."""
    resolved = absolute_url(BASE, "/resultats-courses/x")
    assert "//" not in resolved[len("https://") :]


def test_absolute_url_keeps_an_already_absolute_href_unchanged() -> None:
    href = "https://resultats.breizhchrono.com/documents?reference=1&name=x.pdf"
    assert absolute_url(BASE, href) == href


def test_absolute_url_resolves_a_relative_href_against_the_document_url() -> None:
    document_url = "https://resultats.breizhchrono.com/event/1"
    assert absolute_url(document_url, "resultats-courses/x") == (
        "https://resultats.breizhchrono.com/event/resultats-courses/x"
    )


def test_absolute_url_follows_an_href_that_carries_another_base() -> None:
    """urljoin ignores the base as soon as the href is absolute: the href wins."""
    assert absolute_url(BASE, "https://other.example.com/x") == "https://other.example.com/x"
    assert absolute_url(BASE, "http://resultats.breizhchrono.com/x") == (
        "http://resultats.breizhchrono.com/x"
    )


def test_absolute_url_treats_a_double_leading_slash_as_a_network_path_reference() -> None:
    """``//host`` is scheme-relative, not a path: it replaces the base authority."""
    assert absolute_url(BASE, "//other.example.com/x") == "https://other.example.com/x"
    # Pitfall worth knowing: a path starting with ``//`` is silently turned into a host.
    assert absolute_url(BASE, "//resultats-courses/x") == "https://resultats-courses/x"


def test_absolute_url_returns_the_base_for_an_empty_href() -> None:
    assert absolute_url(BASE, "") == BASE


def test_absolute_url_keeps_non_http_schemes() -> None:
    assert absolute_url(BASE, "mailto:a@b.com") == "mailto:a@b.com"
    assert absolute_url(BASE, "javascript:void(0)") == "javascript:void(0)"


# --- canonicalize_url: identity normalization (storage + HTTP) ---


def test_canonicalize_url_collapses_consecutive_path_slashes() -> None:
    assert canonicalize_url("https://example.com//a//b") == "https://example.com/a/b"


def test_canonicalize_url_sorts_query_parameters() -> None:
    assert canonicalize_url("https://example.com/page?b=2&a=1") == (
        "https://example.com/page?a=1&b=2"
    )


# --- validate_http_scheme: HTTP-only guard ---


@pytest.mark.parametrize("url", ["http://example.com", "https://example.com/page"])
def test_validate_http_scheme_accepts_http_and_https(url: str) -> None:
    validate_http_scheme(url)


@pytest.mark.parametrize("url", ["example.com/page", "/relative", "ftp://example.com/x"])
def test_validate_http_scheme_rejects_non_http_urls(url: str) -> None:
    with pytest.raises(ValueError, match="expected an absolute http:// or https:// URL"):
        validate_http_scheme(url)


def test_supported_http_schemes() -> None:
    assert SUPPORTED_HTTP_SCHEMES == ("http", "https")
