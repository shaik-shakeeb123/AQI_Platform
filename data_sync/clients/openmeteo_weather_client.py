from __future__ import annotations

import asyncio
import email.utils
import random
import time
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Optional, Any, Dict, Tuple
import httpx

from api_layer.config import get_settings
from api_layer.exceptions import ExternalAPIException
from api_layer.logging import get_logger

logger = get_logger(__name__)

_client: httpx.AsyncClient | None = None

# Retry configuration for transient errors.
_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 1.0
_RETRY_MAX_DELAY = 16.0
_RETRYABLE_STATUSES = {500, 502, 503, 504}

# Coordinate-based cache settings
_WEATHER_CACHE_MAX_SIZE = 1000
_WEATHER_CACHE_TTL_SECS = 600.0   # 10 minutes fresh
_WEATHER_STALE_TTL_SECS = 3600.0  # 1 hour stale retention

# Cache structure: key -> (expires_at, stale_until, data_dict)
_weather_cache: OrderedDict[str, tuple[float, float, dict]] = OrderedDict()

# Concurrency locks partitioned by event loop for 100% lifecycle safety
_sharded_locks: list[asyncio.Lock] | None = None
_locks_loop_id: int | None = None

# Shared rate-limiting cooldown state
_cooldown_until: float = 0.0


def _get_lock(key: str) -> asyncio.Lock:
    """Return a concurrency-safe lock for request coalescing on cache misses.
    
    Dynamically binds to the running asyncio loop to guarantee safety across test
    runners and application lifecycles without cross-loop attachment errors.
    """
    global _sharded_locks, _locks_loop_id
    try:
        curr_loop = asyncio.get_running_loop()
        curr_id = id(curr_loop)
    except RuntimeError:
        curr_id = 0
    if _sharded_locks is None or _locks_loop_id != curr_id:
        _sharded_locks = [asyncio.Lock() for _ in range(256)]
        _locks_loop_id = curr_id
    return _sharded_locks[hash(key) % 256]


def _parse_retry_after(header_val: Any, default: float = 60.0) -> float:
    """Parse Retry-After header supporting both delay-seconds and HTTP-date (RFC 7231)."""
    if not header_val:
        return default
    header_str = str(header_val).strip()
    # 1. Delay-seconds integer or float
    try:
        val = float(header_str)
        return max(1.0, val)
    except (ValueError, TypeError):
        pass
    # 2. HTTP-date (e.g. "Wed, 21 Oct 2026 07:28:00 GMT")
    try:
        dt = email.utils.parsedate_to_datetime(header_str)
        if dt is not None:
            now = datetime.now(timezone.utc)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            diff = (dt - now).total_seconds()
            return max(1.0, diff)
    except Exception:
        pass
    return default


def is_rate_limited() -> bool:
    """Return whether Open-Meteo is currently in an active 429 cooldown period."""
    return time.monotonic() < _cooldown_until


def get_cooldown_remaining() -> float:
    """Return remaining seconds in active cooldown (0.0 if not in cooldown)."""
    return max(0.0, _cooldown_until - time.monotonic())


def set_cooldown(seconds: float) -> None:
    """Extend provider cooldown period safely."""
    global _cooldown_until
    new_until = time.monotonic() + max(1.0, seconds)
    if new_until > _cooldown_until:
        _cooldown_until = new_until


def clear_weather_cache() -> None:
    """Clear in-memory weather cache and reset cooldown (primarily for tests)."""
    global _cooldown_until, _sharded_locks, _locks_loop_id
    _weather_cache.clear()
    _cooldown_until = 0.0
    _sharded_locks = None
    _locks_loop_id = None


def _get_from_cache(key: str) -> Optional[dict]:
    """Return fresh cached data if present and not expired."""
    now = time.monotonic()
    if key in _weather_cache:
        expires_at, _, data = _weather_cache[key]
        if now < expires_at:
            _weather_cache.move_to_end(key)
            return data
    return None


def _get_stale_from_cache(key: str) -> Optional[dict]:
    """Return stale cached data if within stale retention window; evicts if permanently expired."""
    now = time.monotonic()
    if key in _weather_cache:
        _, stale_until, data = _weather_cache[key]
        if now < stale_until:
            _weather_cache.move_to_end(key)
            return data
        else:
            # Permanently expired beyond 1 hour; purge from memory
            del _weather_cache[key]
    return None


def _save_to_cache(key: str, data: dict) -> None:
    """Save payload to LRU cache with fresh and stale retention timestamps."""
    now = time.monotonic()
    _weather_cache[key] = (
        now + _WEATHER_CACHE_TTL_SECS,
        now + _WEATHER_STALE_TTL_SECS,
        data,
    )
    if len(_weather_cache) > _WEATHER_CACHE_MAX_SIZE:
        _weather_cache.popitem(last=False)


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(timeout=30.0)
    return _client


async def _get_with_retry(url: str, params: dict, *, error_code: str, label: str) -> dict:
    """GET *url* with exponential back-off + jitter on transient failures, respecting 429 cooldown."""
    last_exc: Exception | None = None
    last_status: int | None = None
    
    lat = params.get("latitude", "unknown")
    lon = params.get("longitude", "unknown")

    for attempt in range(1, _MAX_RETRIES + 1):
        # Fast-fail at start of EVERY attempt if in active cooldown
        cooldown = get_cooldown_remaining()
        if cooldown > 0:
            logger.warning(
                "%s | lat=%s lon=%s | Skipped attempt %d due to active 429 cooldown (%.1fs remaining)",
                label, lat, lon, attempt, cooldown,
            )
            raise ExternalAPIException(
                detail=f"{label}: HTTP 429 Too Many Requests. Upstream provider cooldown active ({cooldown:.1f}s remaining).",
                error_code=error_code,
                status_code=502,
                upstream_status=429,
            )

        try:
            client = _get_client()
            response = await client.get(url, params=params)

            if response.status_code == 429:
                last_status = 429
                retry_after = _parse_retry_after(response.headers.get("Retry-After"), default=60.0)
                set_cooldown(retry_after)
                logger.warning(
                    "%s | lat=%s lon=%s | Attempt %d/%d | HTTP 429 Too Many Requests | Cooldown applied for %.2fs",
                    label, lat, lon, attempt, _MAX_RETRIES, retry_after,
                )
                # Break immediately to avoid burning aggressive retries against a rate-limiting provider
                break

            if response.status_code in _RETRYABLE_STATUSES:
                last_status = response.status_code
                wait = min(
                    _RETRY_BASE_DELAY * (2 ** (attempt - 1)) + random.uniform(0.0, 0.5),
                    _RETRY_MAX_DELAY,
                )
                logger.warning(
                    "%s | lat=%s lon=%s | Attempt %d/%d | HTTP %s | Retry in %.2fs",
                    label, lat, lon, attempt, _MAX_RETRIES, response.status_code, wait,
                )
                await asyncio.sleep(wait)
                continue

            response.raise_for_status()
            return response.json()

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                last_status = 429
                retry_after = _parse_retry_after(e.response.headers.get("Retry-After"), default=60.0)
                set_cooldown(retry_after)
                logger.warning(
                    "%s | lat=%s lon=%s | Attempt %d/%d | HTTP 429 Too Many Requests | Cooldown applied for %.2fs",
                    label, lat, lon, attempt, _MAX_RETRIES, retry_after,
                )
                break

            logger.error(
                "%s | lat=%s lon=%s | Attempt %d/%d | HTTP %s | Fatal Error",
                label, lat, lon, attempt, _MAX_RETRIES, e.response.status_code,
            )
            last_exc = e
            break  # non-retryable 4xx
        except httpx.RequestError as e:
            last_exc = e
            last_status = None
            wait = min(
                _RETRY_BASE_DELAY * (2 ** (attempt - 1)) + random.uniform(0.0, 0.5),
                _RETRY_MAX_DELAY,
            )
            logger.warning(
                "%s | lat=%s lon=%s | Attempt %d/%d | %s | Retry in %.2fs",
                label, lat, lon, attempt, _MAX_RETRIES, e.__class__.__name__, wait,
            )
            if attempt < _MAX_RETRIES:
                await asyncio.sleep(wait)

    if last_status == 429:
        cooldown_sec = get_cooldown_remaining()
        raise ExternalAPIException(
            detail=f"{label}: HTTP 429 Too Many Requests. The upstream weather provider is currently rate limiting requests (cooldown {cooldown_sec:.1f}s).",
            error_code=error_code,
            status_code=502,
            upstream_status=429,
        )
    elif last_status is not None:
        raise ExternalAPIException(
            detail=f"{label}: HTTP {last_status}",
            error_code=error_code,
            status_code=502,
            upstream_status=last_status,
        )
    elif isinstance(last_exc, httpx.HTTPStatusError):
        raise ExternalAPIException(
            detail=f"{label}: HTTP {last_exc.response.status_code}",
            error_code=error_code,
            status_code=502,
            upstream_status=last_exc.response.status_code,
        )
        
    err_type = last_exc.__class__.__name__ if last_exc else "Unknown"
    err_msg = str(last_exc) if last_exc else "unknown error"
    raise ExternalAPIException(
        detail=f"{label}: connection failed after {_MAX_RETRIES} attempts ({err_type}: {err_msg})",
        error_code=error_code,
        status_code=502,
    )


class OpenMeteoWeatherClient:
    """Client for interacting with the Open-Meteo Weather API with shared caching and cooldown protection."""

    def __init__(self) -> None:
        settings = get_settings()
        self.base_url: str = settings.OPEN_METEO_BASE_URL

    async def fetch_current_weather(
        self,
        latitude: float,
        longitude: float,
    ) -> dict:
        """Fetch current weather data for a given location.

        Returns a dict with ``current`` (real-time conditions) and ``daily``
        (sunrise / sunset for today) keys, among others.
        Uses coordinate-based caching and request coalescing to eliminate duplicate upstream traffic.
        """
        cache_key = f"current:{round(latitude, 2)}:{round(longitude, 2)}"
        lock = _get_lock(cache_key)

        async with lock:
            cached = _get_from_cache(cache_key)
            if cached is not None:
                return cached

            if is_rate_limited():
                stale = _get_stale_from_cache(cache_key)
                if stale is not None:
                    logger.warning(
                        "Open-Meteo in 429 cooldown. Serving stale cache for coords=(%s, %s)",
                        latitude, longitude,
                    )
                    return stale
                cooldown_sec = get_cooldown_remaining()
                raise ExternalAPIException(
                    detail=f"Open-Meteo Weather API: HTTP 429 Too Many Requests. Upstream provider cooldown active ({cooldown_sec:.1f}s remaining).",
                    error_code="OPEN_METEO_API_ERROR",
                    status_code=502,
                    upstream_status=429,
                )

            url = f"{self.base_url}/forecast"
            params: dict[str, str | float | str] = {
                "latitude": latitude,
                "longitude": longitude,
                "current": (
                    "temperature_2m,apparent_temperature,relative_humidity_2m,"
                    "wind_speed_10m,wind_direction_10m,surface_pressure,"
                    "precipitation,cloud_cover,weather_code"
                ),
                "daily": "sunrise,sunset",
                "timezone": "auto",
                "forecast_days": 1,
            }
            try:
                data = await _get_with_retry(
                    url, params,
                    error_code="OPEN_METEO_API_ERROR",
                    label="Open-Meteo Weather API",
                )
                _save_to_cache(cache_key, data)
                return data
            except ExternalAPIException as exc:
                stale = _get_stale_from_cache(cache_key)
                if stale is not None:
                    logger.warning(
                        "Open-Meteo API failed (%s). Serving stale cache for coords=(%s, %s)",
                        exc.detail, latitude, longitude,
                    )
                    return stale
                raise

    async def fetch_batch_current_weather(
        self,
        latitudes: list[float],
        longitudes: list[float],
    ) -> list[dict]:
        """Fetch current weather data for multiple locations in a single batch request."""
        if not latitudes or not longitudes or len(latitudes) != len(longitudes):
            return []
            
        url = f"{self.base_url}/forecast"
        params: dict[str, str | float] = {
            "latitude": ",".join(str(lat) for lat in latitudes),
            "longitude": ",".join(str(lon) for lon in longitudes),
            "current": (
                "temperature_2m,relative_humidity_2m,"
                "wind_speed_10m,wind_direction_10m,surface_pressure,precipitation,cloud_cover"
            ),
            "timezone": "auto",
        }
        try:
            data = await _get_with_retry(
                url, params,
                error_code="OPEN_METEO_BATCH_ERROR",
                label="Open-Meteo Batch Weather API",
            )
            result = data if isinstance(data, list) else [data]
            for lat, lon, item in zip(latitudes, longitudes, result):
                if isinstance(item, dict) and "current" in item:
                    _save_to_cache(f"current:{round(lat, 2)}:{round(lon, 2)}", item)
            return result
        except Exception as e:
            logger.error("Open-Meteo batch API error: %s", str(e))
            raise

    async def fetch_hourly_weather(
        self,
        latitude: float,
        longitude: float,
        forecast_days: int = 1,
    ) -> dict:
        """Fetch hourly weather forecast for a given location.
        Uses coordinate-based caching and request coalescing.
        """
        cache_key = f"hourly:{round(latitude, 2)}:{round(longitude, 2)}:{forecast_days}"
        lock = _get_lock(cache_key)

        async with lock:
            cached = _get_from_cache(cache_key)
            if cached is not None:
                return cached

            if is_rate_limited():
                stale = _get_stale_from_cache(cache_key)
                if stale is not None:
                    logger.warning(
                        "Open-Meteo in 429 cooldown. Serving stale hourly cache for coords=(%s, %s)",
                        latitude, longitude,
                    )
                    return stale
                cooldown_sec = get_cooldown_remaining()
                raise ExternalAPIException(
                    detail=f"Open-Meteo Hourly Weather API: HTTP 429 Too Many Requests. Upstream provider cooldown active ({cooldown_sec:.1f}s remaining).",
                    error_code="OPEN_METEO_API_ERROR",
                    status_code=502,
                    upstream_status=429,
                )

            url = f"{self.base_url}/forecast"
            params: dict[str, str | float | int] = {
                "latitude": latitude,
                "longitude": longitude,
                "hourly": (
                    "temperature_2m,relative_humidity_2m,"
                    "wind_speed_10m,wind_direction_10m,surface_pressure,precipitation,cloud_cover"
                ),
                "forecast_days": forecast_days,
                "timezone": "auto",
            }
            try:
                data = await _get_with_retry(
                    url, params,
                    error_code="OPEN_METEO_API_ERROR",
                    label="Open-Meteo Hourly Weather API",
                )
                _save_to_cache(cache_key, data)
                return data
            except ExternalAPIException as exc:
                stale = _get_stale_from_cache(cache_key)
                if stale is not None:
                    logger.warning(
                        "Open-Meteo Hourly API failed (%s). Serving stale cache for coords=(%s, %s)",
                        exc.detail, latitude, longitude,
                    )
                    return stale
                raise
