import re

# Marker found in the temporary maintenance page served with a successful (2xx) status
# by the BreizhChrono website (e.g. "On revient très vite !").
MAINTENANCE_PAGE_MARKER = "On revient très vite"


def normalize_breizhchrono(url: str, content: str) -> str:
    # usefull only for event list page, to avoid snapshot creation
    # on each fetch due to timestamp changes in the js code
    content = re.sub(r"ts=\d+", "ts=__TS__", content)
    return content


def is_temporary_unavailable_page(url: str, content: str) -> bool:
    """Flag BreizhChrono maintenance pages returned with a successful HTTP status.

    The website sometimes answers ``200 OK`` with a temporary maintenance page. Such a
    page must not be cached nor snapshotted, and the fetch must be retried.
    """
    return MAINTENANCE_PAGE_MARKER in content
