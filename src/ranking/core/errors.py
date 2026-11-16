class ExternalRedirectError(Exception):
    """The crawler refused to leave the configured site.

    Raised either when the requested URL itself targets another host (``requested_url`` equals
    ``final_url``; refused before any network access) or when the server redirected the request to
    another host. Both cases are recovered the same way: the link is skipped and the crawl
    continues, so a single external link never aborts the crawl.
    """

    def __init__(self, requested_url: str, final_url: str):
        self.requested_url = requested_url
        self.final_url = final_url

        if requested_url == final_url:
            # Not a redirect: the requested link directly points at another host.
            message = f"Refused external URL: {requested_url} (outside the allowed site)"
        else:
            message = f"External redirect: {requested_url} → {final_url}"
        super().__init__(message)


class LocalServerErrorException(RuntimeError):
    """A target URL returns a server error while the rest of the website is healthy.

    Raised when the target URL responds with an HTTP 5xx status code (typically 500) but a
    reference page (see ``CheckPage``) still responds normally. This points to a localized
    application bug on the target page rather than a global site outage, so the crawler must
    fail immediately instead of retrying the broken URL.

    It is a :class:`RuntimeError` subclass so callers already handling fetch failures (e.g. the
    CLI, which records the page as failed) keep working, while still being able to distinguish
    this case precisely.
    """

    def __init__(self, requested_url: str, status_code: int = 500):
        self.requested_url = requested_url
        self.status_code = status_code

        super().__init__(
            f"Local server error {status_code} for URL: {requested_url} "
            "(reference page is healthy, no retry)"
        )
