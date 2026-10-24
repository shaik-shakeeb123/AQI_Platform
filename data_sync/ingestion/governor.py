"""Provider-aware request governor for rate limiting, backoff, and hourly budget accounting."""

from __future__ import annotations

import asyncio
import collections
import random
import time
from typing import Callable, Coroutine, Any, TypeVar, Optional, Deque
import httpx
from api_layer.exceptions import ExternalAPIException
from api_layer.logging import get_logger

logger = get_logger(__name__)

T = TypeVar("T")

class RequestGovernor:
    """Controls concurrency, rate limits, hourly budget, and retries for external providers.
    
    Enforces dual-horizon protection:
    1. Per-minute proactive pacing (e.g., 45 RPM -> minimum 1.33s interval).
    2. Hourly total request quota (e.g., 1800 req/hr against provider's 2000 limit).
    3. Coordinated multi-worker pause upon HTTP 429 / Retry-After.
    4. Fast-fail halt on HTTP 401 / 403 to prevent abusive retries against restricted accounts.
    5. Accounting for every attempted outbound HTTP request (including retries and errors).
    """

    def __init__(
        self,
        provider_name: str,
        max_concurrency: int = 10,
        requests_per_minute: int = 45,
        hourly_budget: int = 1800,
        max_retries: int = 3,
        base_backoff: float = 1.0,
        metrics: Any = None,
    ) -> None:
        self.provider_name = provider_name
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._max_retries = max_retries
        self._base_backoff = base_backoff
        self.metrics = metrics
        
        # Rate limit configuration
        self.requests_per_minute = requests_per_minute
        self._min_request_interval = 60.0 / self.requests_per_minute if self.requests_per_minute > 0 else 0
        self.hourly_budget = hourly_budget
        
        # State coordination
        self._rate_limit_lock = asyncio.Lock()
        self._pause_until: float = 0.0
        self._last_request_time: float = 0.0
        
        # Rolling request accounting for hourly quota (timestamps of attempts within last 3600s)
        self._request_timestamps: Deque[float] = collections.deque()
        
        # Global provider health state: READY, RATE_LIMITED, AUTHENTICATION_ERROR, ACCESS_DENIED
        self.provider_state: str = "READY"

    @property
    def current_hourly_usage(self) -> int:
        """Return the count of requests made in the trailing 60-minute window."""
        now = time.time()
        one_hour_ago = now - 3600.0
        # Prune older than 1h
        while self._request_timestamps and self._request_timestamps[0] <= one_hour_ago:
            self._request_timestamps.popleft()
        return len(self._request_timestamps)

    async def _wait_and_pace(self) -> None:
        """Wait if paused globally, verify hourly quota, and pace per-minute requests proactively."""
        async with self._rate_limit_lock:
            # 0. Fast-fail if provider is in a hard failure state
            if self.provider_state in ("AUTHENTICATION_ERROR", "ACCESS_DENIED"):
                raise ExternalAPIException(
                    detail=f"{self.provider_name} requests halted due to {self.provider_state}. Operator intervention required.",
                    error_code=self.provider_state,
                    status_code=502,
                )

            now = time.time()
            
            # 1. Wait if we are in a global 429 / header-directed pause
            if now < self._pause_until:
                sleep_time = self._pause_until - now
                if self.metrics:
                    self.metrics.rate_limit_pauses = getattr(self.metrics, "rate_limit_pauses", 0) + 1
                logger.warning(
                    "[%s Governor] Globally paused. Waiting %.2fs before admitting next request.", 
                    self.provider_name, sleep_time
                )
                await asyncio.sleep(sleep_time)
                now = time.time()

            # 2. Hourly Budget Accounting & Protection
            one_hour_ago = now - 3600.0
            while self._request_timestamps and self._request_timestamps[0] <= one_hour_ago:
                self._request_timestamps.popleft()

            if len(self._request_timestamps) >= self.hourly_budget:
                oldest = self._request_timestamps[0]
                wait_time = max(1.0, 3600.0 - (now - oldest) + 1.0)
                if self.metrics:
                    self.metrics.hourly_budget_pauses = getattr(self.metrics, "hourly_budget_pauses", 0) + 1
                logger.warning(
                    "[%s Governor] Hourly budget reached (%d/%d requests in trailing hour). Pausing for %.2fs until window rolls over.",
                    self.provider_name, len(self._request_timestamps), self.hourly_budget, wait_time
                )
                self.provider_state = "RATE_LIMITED"
                await asyncio.sleep(wait_time)
                now = time.time()
                
            # 3. Proactive pacing (Leaky Bucket for per-minute rate limit)
            elapsed = now - self._last_request_time
            if elapsed < self._min_request_interval:
                delay = self._min_request_interval - elapsed
                if self.metrics:
                    self.metrics.requests_delayed_by_rate_limiter = getattr(self.metrics, "requests_delayed_by_rate_limiter", 0) + 1
                await asyncio.sleep(delay)
                
            self._last_request_time = time.time()
            
            if self.metrics:
                self.metrics.requests_admitted = getattr(self.metrics, "requests_admitted", 0) + 1

    def _record_attempt(self) -> None:
        """Record an outbound HTTP attempt into rolling window and metrics."""
        now = time.time()
        self._request_timestamps.append(now)
        if self.metrics:
            self.metrics.openaq_requests = getattr(self.metrics, "openaq_requests", 0) + 1

    def _apply_rate_limit(self, retry_after: float) -> None:
        """Pause all future requests until the retry_after period elapses."""
        now = time.time()
        new_pause_until = now + retry_after
        if new_pause_until > self._pause_until + 1.0:
            self._pause_until = new_pause_until
            self.provider_state = "RATE_LIMITED"
            logger.warning(
                "[%s Governor] Global rate-limit pause applied for %.2fs", 
                self.provider_name, retry_after
            )

    def _track_headers(self, response: httpx.Response) -> None:
        """Update metrics and proactively apply rate limits based on provider headers."""
        headers = response.headers
        try:
            if self.metrics:
                if "X-Ratelimit-Limit" in headers:
                    self.metrics.current_rate_limit = int(headers["X-Ratelimit-Limit"])
                if "X-Ratelimit-Remaining" in headers:
                    self.metrics.current_remaining = int(headers["X-Ratelimit-Remaining"])
                if "X-Ratelimit-Reset" in headers:
                    self.metrics.current_reset_seconds = int(headers["X-Ratelimit-Reset"])
                    
            # Proactive pause if remaining is zero or dangerously low
            if "X-Ratelimit-Remaining" in headers and "X-Ratelimit-Reset" in headers:
                remaining = int(headers["X-Ratelimit-Remaining"])
                if remaining <= 1:
                    reset_val = float(headers["X-Ratelimit-Reset"])
                    if reset_val > 1000000000:
                        retry_after = max(0.0, reset_val - time.time())
                    else:
                        retry_after = reset_val
                    
                    if retry_after > 0:
                        self._apply_rate_limit(retry_after + 1.0)
                        
        except (ValueError, TypeError):
            pass

    async def execute(
        self, 
        operation: Callable[[], Coroutine[Any, Any, T]],
        on_retry: Callable[[], None] | None = None,
        on_error: Callable[[], None] | None = None,
    ) -> T:
        """Execute an async HTTP operation with full rate governance, budget tracking, and error handling."""
        
        for attempt in range(1, self._max_retries + 1):
            
            # Request admission control (must be outside the concurrency semaphore)
            await self._wait_and_pace()
            
            async with self._semaphore:
                if self.metrics:
                    self.metrics.requests_in_flight = getattr(self.metrics, "requests_in_flight", 0) + 1
                    
                # Account for outbound attempt (every attempt, whether it succeeds or fails)
                self._record_attempt()
                
                try:
                    res = await operation()
                    
                    if hasattr(res, "headers"):
                        self._track_headers(res)
                        
                    if self.metrics:
                        self.metrics.requests_completed = getattr(self.metrics, "requests_completed", 0) + 1
                    self.provider_state = "READY"
                    return res
                    
                except httpx.HTTPStatusError as e:
                    self._track_headers(e.response)
                    status = e.response.status_code
                    
                    if status == 429:
                        if self.metrics:
                            self.metrics.count_429 = getattr(self.metrics, "count_429", 0) + 1
                            if attempt > 1:
                                self.metrics.count_429_retry = getattr(self.metrics, "count_429_retry", 0) + 1
                                
                        retry_after = 60.0
                        headers = e.response.headers
                        if "Retry-After" in headers:
                            try:
                                retry_after = float(headers["Retry-After"])
                            except ValueError:
                                pass
                        elif "X-Ratelimit-Reset" in headers:
                            try:
                                reset_val = float(headers["X-Ratelimit-Reset"])
                                if reset_val > 1000000000:
                                    retry_after = max(0.0, reset_val - time.time())
                                else:
                                    retry_after = reset_val
                            except ValueError:
                                pass
                                
                        # Safety margin + jitter
                        retry_after += 1.0 + random.uniform(0.1, 0.5)
                        
                        # Apply coordinated global pause lock
                        async with self._rate_limit_lock:
                            self._apply_rate_limit(retry_after)
                            
                        if attempt == self._max_retries:
                            if on_error:
                                on_error()
                            raise ExternalAPIException(
                                detail=f"{self.provider_name} rate limit exceeded after {self._max_retries} attempts.",
                                error_code="RATE_LIMITED",
                                status_code=502,
                                upstream_status=429
                            )
                        if on_retry:
                            on_retry()
                        continue
                        
                    if status in (401, 403):
                        # 401/403: Stop immediately! Do NOT retry against restricted or invalid credentials.
                        self.provider_state = "AUTHENTICATION_ERROR" if status == 401 else "ACCESS_DENIED"
                        if self.metrics:
                            if status == 401:
                                self.metrics.count_401 = getattr(self.metrics, "count_401", 0) + 1
                            else:
                                self.metrics.count_403 = getattr(self.metrics, "count_403", 0) + 1
                        if on_error:
                            on_error()
                        raise ExternalAPIException(
                            detail=f"{self.provider_name} authentication/authorization failed (HTTP {status}). Ingestion halted.",
                            error_code="AUTHENTICATION_FAILED" if status == 401 else "FORBIDDEN",
                            status_code=502,
                            upstream_status=status
                        )
                        
                    if status >= 500:
                        self.provider_state = "TEMPORARY_UPSTREAM_FAILURE"
                        if self.metrics:
                            self.metrics.count_5xx = getattr(self.metrics, "count_5xx", 0) + 1
                        if attempt == self._max_retries:
                            if on_error:
                                on_error()
                            raise ExternalAPIException(
                                detail=f"{self.provider_name} server error {status}.",
                                error_code="PROVIDER_ERROR",
                                status_code=502,
                                upstream_status=status
                            )
                        if on_retry:
                            on_retry()
                        # Exponential backoff with jitter
                        delay = self._base_backoff * (2 ** (attempt - 1)) + random.uniform(0.05, 0.25)
                        await asyncio.sleep(delay)
                        continue
                        
                    if on_error:
                        on_error()
                    raise ExternalAPIException(
                        detail=f"{self.provider_name} client error {status}.",
                        error_code="BAD_REQUEST",
                        status_code=502,
                        upstream_status=status
                    )
                    
                except (httpx.RequestError, asyncio.TimeoutError) as e:
                    self.provider_state = "TEMPORARY_UPSTREAM_FAILURE"
                    if attempt == self._max_retries:
                        if on_error:
                            on_error()
                        raise ExternalAPIException(
                            detail=f"{self.provider_name} network error: {str(e)}",
                            error_code="NETWORK_ERROR",
                            status_code=502,
                        )
                    if on_retry:
                        on_retry()
                    delay = self._base_backoff * (2 ** (attempt - 1)) + random.uniform(0.05, 0.25)
                    await asyncio.sleep(delay)
                    
                finally:
                    if self.metrics:
                        self.metrics.requests_in_flight = max(0, getattr(self.metrics, "requests_in_flight", 1) - 1)
                        
        raise RuntimeError(f"[{self.provider_name} Governor] Loop exited unexpectedly")
