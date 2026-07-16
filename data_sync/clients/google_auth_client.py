from __future__ import annotations
from google.auth.transport import requests as google_requests

class GoogleAuthClient:
    """Centralized client representing external HTTP operations for Google OAuth verification."""

    def __init__(self) -> None:
        self.request = google_requests.Request()

    def get_request(self) -> google_requests.Request:
        """Return the transport request object for verifying tokens."""
        return self.request
