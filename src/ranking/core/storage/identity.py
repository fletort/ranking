from __future__ import annotations

import hashlib
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse


def canonicalize_url(url: str) -> str:
    """Canonicalize a URL by sorting query parameters to stabilize resource IDs.

    Semantically equivalent URLs (e.g. the same query parameters in a different
    order) must produce the exact same canonical form.
    """
    parsed = urlparse(url)
    sorted_query = sorted(parse_qsl(parsed.query, keep_blank_values=True))
    canonical_query = urlencode(sorted_query, doseq=True)
    return urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            canonical_query,
            parsed.fragment,
        )
    )


def compute_resource_id(url: str) -> str:
    """Derive a deterministic SHA-1 resource ID from a canonicalized URL.

    The same URL must always generate the same Resource ID across runs so that
    cache usability and storage consistency are preserved.
    """
    canonical = canonicalize_url(url)
    return hashlib.sha1(canonical.encode("utf-8")).hexdigest()  # noqa: S324


__all__ = ["canonicalize_url", "compute_resource_id"]
