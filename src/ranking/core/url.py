from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

# Schemes the crawler is allowed to request over the network.
SUPPORTED_HTTP_SCHEMES = ("http", "https")


def canonicalize_url(url: str) -> str:
    """Return the canonical form of *url*: the single URL normalization of the Core layer.

    Consecutive slashes in the URL path are collapsed (``https://host//path`` becomes
    ``https://host/path``) and the query parameters are sorted. The scheme
    (``http://`` / ``https://``), the parameters themselves and the fragment are preserved.

    Both the Storage identity (:meth:`StorageProvider.compute_resource_id`) and the HTTP client
    (:func:`ranking.core.crawler.httpx.normalize_url`) call this function, so a URL requested on
    the network is always exactly the URL its Resource ID is computed from. Keeping a single
    implementation prevents the two layers from diverging.
    """
    parsed = urlparse(url)
    canonical_path = re.sub(r"/+", "/", parsed.path)
    sorted_query = sorted(parse_qsl(parsed.query, keep_blank_values=True))
    canonical_query = urlencode(sorted_query, doseq=True)
    return urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            canonical_path,
            parsed.params,
            canonical_query,
            parsed.fragment,
        )
    )


def validate_http_scheme(url: str) -> None:
    """Raise ``ValueError`` when *url* is not an absolute ``http`` / ``https`` URL.

    Used by the HTTP client before any network access, so an invalid URL fails immediately
    instead of being sent to the transport (and retried).
    """
    scheme = urlparse(url).scheme
    if scheme not in SUPPORTED_HTTP_SCHEMES:
        raise ValueError(f"Invalid URL {url!r}: expected an absolute http:// or https:// URL")


def absolute_url(base_url: str, href: str) -> str:
    """Resolve *href* against *base_url* and return the resulting absolute URL.

    Generic link-resolution mechanism shared by the plugins: it resolves exactly what a browser
    would, so a relative href (``/resultats-courses/...``) becomes absolute against *base_url*.
    Plugins therefore only supply their base URL and never concatenate strings themselves, which
    is what produced the duplicated ``https://host//path`` separator in the first place.

    Args:
        base_url: The URL the href is resolved against. Use the document URL when crawling a page,
            or the site root (with a trailing slash) when the site emits root-relative hrefs.
        href: The raw href extracted from the page.

    Returns:
        The resolved absolute URL.

    Note:
        ``urljoin`` follows RFC 3986, so the result does **not** necessarily stay on *base_url*:
        an href carrying a scheme (``https://other``) or a network-path reference (``//other``)
        yields a URL on another host, and a non-http scheme (``mailto:``, ``javascript:``) is
        returned as-is. Callers that must stay on one site should validate the result (e.g. a
        same-domain check); the HTTP client rejects non ``http(s)`` URLs. Finally, internal
        duplicate slashes in the path are not collapsed here: that is the single responsibility of
        :func:`canonicalize_url`.
    """
    return urljoin(base_url, href)


__all__ = [
    "SUPPORTED_HTTP_SCHEMES",
    "absolute_url",
    "canonicalize_url",
    "validate_http_scheme",
]
