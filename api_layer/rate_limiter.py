"""Zero-dependency in-process rate limiter for FastAPI.

Implements a fixed-window per-IP rate limiter as ASGI middleware.
This is intentionally simple: it uses a plain ``defaultdict`` keyed by
``(client_ip, path_prefix, minute_bucket)`` so the memory footprint stays
bounded to ``O(unique_IPs * tracked_endpoints)`` per minute window.

The window resets automatically because old bucket keys are never accessed
again once the minute ticks over — they will be garbage-collected.

Protected routes (configurable):
    * /auth/login
    * /auth/register

Behavior:
    * Returns HTTP 429 with a ``Retry-After`` header when the limit is exceeded.
    * Passes all other requests through unchanged.
    * Does not rate-limit internal or non-auth paths.
"""

from __future__ import annotations

import time
from collections import defaultdict
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

# Paths subject to rate limiting.
_RATE_LIMITED_PATHS = {"/auth/login", "/auth/register"}


class AuthRateLimitMiddleware(BaseHTTPMiddleware):
    """ASGI middleware that rate-limits auth endpoints by remote IP.

    Args:
        app: The ASGI application to wrap.
        max_requests: Maximum number of requests allowed per IP per minute
            on any rate-limited path.  Defaults to 10.
    """

    def __init__(self, app: Callable, max_requests: int = 10) -> None:
        super().__init__(app)
        self.max_requests = max_requests
        # counter[(ip, path, minute_bucket)] -> request count
        # Stale buckets are pruned when the dict grows large to prevent
        # unbounded memory accumulation under sustained or attack traffic.
        self._counters: defaultdict[tuple, int] = defaultdict(int)

    def _prune_stale_buckets(self, current_bucket: int) -> None:
        """Remove counter entries from previous minute windows.

        Called when the counters dict grows large (> 500 keys) to prevent
        unbounded memory growth under sustained high-traffic or attack loads.
        Only entries from buckets older than ``current_bucket`` are removed.
        """
        stale_keys = [
            k for k in self._counters
            if k[2] < current_bucket  # k[2] is the minute_bucket field
        ]
        for k in stale_keys:
            del self._counters[k]

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        path = request.url.path

        # Only intercept paths we care about.
        if path not in _RATE_LIMITED_PATHS:
            return await call_next(request)

        # Derive the client IP, respecting X-Forwarded-For set by Render's proxy.
        client_ip = request.headers.get("X-Forwarded-For", "")
        if client_ip:
            client_ip = client_ip.split(",")[0].strip()
        else:
            client_ip = (request.client.host if request.client else "unknown")

        # Fixed 1-minute bucket: floor(monotonic_time / 60)
        minute_bucket = int(time.monotonic() // 60)
        key = (client_ip, path, minute_bucket)

        self._counters[key] += 1

        # Prune stale buckets if the dict grows large to bound memory usage.
        if len(self._counters) > 500:
            self._prune_stale_buckets(minute_bucket)

        if self._counters[key] > self.max_requests:
            return JSONResponse(
                status_code=429,
                content={
                    "error": {
                        "code": "RATE_LIMIT_EXCEEDED",
                        "message": (
                            f"Too many requests. Maximum {self.max_requests} "
                            "requests per minute allowed on this endpoint."
                        ),
                        "path": path,
                    }
                },
                headers={"Retry-After": "60"},
            )

        return await call_next(request)
