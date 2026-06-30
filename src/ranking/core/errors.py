class ExternalRedirectError(Exception):
    def __init__(self, requested_url: str, final_url: str):
        self.requested_url = requested_url
        self.final_url = final_url

        super().__init__(f"External redirect: {requested_url} → {final_url}")
