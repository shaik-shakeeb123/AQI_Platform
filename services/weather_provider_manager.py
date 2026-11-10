from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Optional, Any, Dict, List, Tuple

from api_layer.logging import get_logger
from data_sync.clients.base_weather_provider import BaseWeatherProvider
from data_sync.clients.met_norway_client import MetNorwayClient
from data_sync.clients.openmeteo_provider import OpenMeteoProvider
from data_sync.models.weather_models import (
    NormalizedCurrentWeather,
    NormalizedHourlyForecast,
)

logger = get_logger(__name__)

# Cache configuration
_WEATHER_CACHE_MAX_SIZE = 1000
_WEATHER_CACHE_TTL_SECS = 600.0   # 10 minutes fresh
_WEATHER_STALE_TTL_SECS = 3600.0  # 1 hour stale retention

# Shared Coordinate Cache:
# key -> (expires_at, stale_until, created_at, NormalizedCurrentWeather)
_shared_current_cache: OrderedDict[str, tuple[float, float, float, NormalizedCurrentWeather]] = OrderedDict()

# Shared Hourly Cache:
# key -> (expires_at, stale_until, created_at, List[NormalizedHourlyForecast])
_shared_hourly_cache: OrderedDict[str, tuple[float, float, float, List[NormalizedHourlyForecast]]] = OrderedDict()

# Sharded concurrency locks partitioned by event loop for 100% lifecycle safety
_sharded_locks: list[asyncio.Lock] | None = None
_locks_loop_id: int | None = None

# Manager operational telemetry metrics
_manager_metrics: dict[str, Any] = {
    "primary_requests": 0,
    "primary_successes": 0,
    "primary_failures": 0,
    "secondary_requests": 0,
    "secondary_successes": 0,
    "secondary_failures": 0,
    "cache_hits": 0,
    "cache_misses": 0,
    "stale_cache_hits": 0,
    "unavailable_responses": 0,
    "fallback_events": 0,
    "coalesced_requests": 0,
}


def _get_lock(key: str) -> asyncio.Lock:
    """Return a concurrency lock for request coalescing on cache misses."""
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


def get_manager_metrics() -> dict[str, Any]:
    """Return a snapshot of current weather provider manager operational telemetry."""
    return dict(_manager_metrics)


def reset_manager_metrics() -> None:
    """Reset operational telemetry counters (primarily for tests)."""
    for k in _manager_metrics:
        _manager_metrics[k] = 0


def clear_shared_weather_cache() -> None:
    """Clear shared in-memory weather caches and reset locks (primarily for tests)."""
    global _sharded_locks, _locks_loop_id
    _shared_current_cache.clear()
    _shared_hourly_cache.clear()
    _sharded_locks = None
    _locks_loop_id = None
    reset_manager_metrics()


class WeatherProviderManager:
    """Orchestrates multi-provider weather intelligence with intelligent fallback and shared caching."""

    def __init__(
        self,
        primary_provider: Optional[BaseWeatherProvider] = None,
        secondary_provider: Optional[BaseWeatherProvider] = None,
        cache_ttl_secs: float = _WEATHER_CACHE_TTL_SECS,
        stale_ttl_secs: float = _WEATHER_STALE_TTL_SECS,
    ) -> None:
        from api_layer.config import get_settings
        settings = get_settings()

        if primary_provider is not None:
            self.primary = primary_provider
        else:
            p_name = getattr(settings, "WEATHER_PRIMARY_PROVIDER", "MET_NORWAY").upper()
            if p_name == "OPEN_METEO":
                self.primary = OpenMeteoProvider()
            else:
                self.primary = MetNorwayClient()

        if secondary_provider is not None:
            self.secondary = secondary_provider
        else:
            s_name = getattr(settings, "WEATHER_SECONDARY_PROVIDER", "OPEN_METEO").upper()
            if s_name == "MET_NORWAY":
                self.secondary = MetNorwayClient()
            else:
                self.secondary = OpenMeteoProvider()

        self.cache_ttl_secs = cache_ttl_secs
        self.stale_ttl_secs = stale_ttl_secs

    @staticmethod
    def format_coord_key(lat: float, lon: float) -> str:
        """Format coordinates into a standardized 2-decimal cache key."""
        return f"{round(lat, 2):.2f}_{round(lon, 2):.2f}"

    def _get_from_current_cache(self, key: str) -> Optional[NormalizedCurrentWeather]:
        now = time.monotonic()
        if key in _shared_current_cache:
            entry = _shared_current_cache[key]
            expires_at = entry[0]
            if now < expires_at:
                _shared_current_cache.move_to_end(key)
                _manager_metrics["cache_hits"] += 1
                weather_clone = entry[3]
                # Return with source=CACHE and preserve cached_at
                weather_clone.source = "CACHE"
                logger.info("Shared Weather Cache HIT | key=%s | source=CACHE", key)
                return weather_clone
        return None

    def _get_stale_from_current_cache(self, key: str) -> Optional[NormalizedCurrentWeather]:
        now = time.monotonic()
        if key in _shared_current_cache:
            entry = _shared_current_cache[key]
            stale_until = entry[1]
            if now < stale_until:
                _shared_current_cache.move_to_end(key)
                _manager_metrics["stale_cache_hits"] += 1
                weather_clone = entry[3]
                weather_clone.source = "STALE_CACHE"
                weather_clone.is_available = True
                logger.warning(
                    "Shared Weather STALE Cache served | key=%s | source=STALE_CACHE", key
                )
                return weather_clone
            else:
                del _shared_current_cache[key]
        return None

    def _save_to_current_cache(self, key: str, data: NormalizedCurrentWeather) -> None:
        now = time.monotonic()
        data.cached_at = datetime.now(timezone.utc).isoformat()
        _shared_current_cache[key] = (
            now + self.cache_ttl_secs,
            now + self.stale_ttl_secs,
            now,
            data,
        )
        if len(_shared_current_cache) > _WEATHER_CACHE_MAX_SIZE:
            _shared_current_cache.popitem(last=False)

    async def get_current_weather(
        self, lat: float, lon: float
    ) -> NormalizedCurrentWeather:
        """Retrieve current weather via multi-provider failover chain.
        
        Resolution sequence:
        1. Shared Cache (Fresh HIT, TTL: 10m)
        2. Primary Provider (MET Norway)
        3. Secondary Provider (Open-Meteo) on failure or rate-limit
        4. Shared Cache (Stale HIT, TTL: 1h)
        5. Controlled UNAVAILABLE (HTTP 200, is_available=False)
        """
        key = self.format_coord_key(lat, lon)

        # 1. Fast path: check fresh cache before acquiring lock
        cached = self._get_from_current_cache(key)
        if cached is not None:
            return cached

        _manager_metrics["cache_misses"] += 1
        lock = _get_lock(key)

        async with lock:
            # 2. Re-check fresh cache inside lock (in case another coroutine just resolved it)
            cached = self._get_from_current_cache(key)
            if cached is not None:
                _manager_metrics["coalesced_requests"] += 1
                return cached

            # 3. Attempt Primary Provider (MET Norway)
            primary_name = self.primary.get_provider_name()
            if not self.primary.is_rate_limited():
                try:
                    _manager_metrics["primary_requests"] += 1
                    t0 = time.perf_counter()
                    weather = await self.primary.fetch_current_weather(lat, lon)
                    dur_ms = (time.perf_counter() - t0) * 1000.0
                    _manager_metrics["primary_successes"] += 1
                    weather.source = "MET_NORWAY"
                    self._save_to_current_cache(key, weather)
                    logger.info(
                        "Weather Provider Success | provider=%s | coords=(%.2f, %.2f) | duration=%.1fms",
                        primary_name, lat, lon, dur_ms
                    )
                    return weather
                except Exception as e:
                    _manager_metrics["primary_failures"] += 1
                    _manager_metrics["fallback_events"] += 1
                    logger.warning(
                        "Primary provider %s failed for coords=(%.2f, %.2f): %s. Triggering fallback to secondary provider...",
                        primary_name, lat, lon, str(e)
                    )
            else:
                _manager_metrics["fallback_events"] += 1
                rem = self.primary.get_cooldown_remaining()
                logger.info(
                    "Primary provider %s is in active cooldown (%.1fs remaining). Bypassing to secondary provider...",
                    primary_name, rem
                )

            # 4. Attempt Secondary Provider (Open-Meteo)
            secondary_name = self.secondary.get_provider_name()
            if not self.secondary.is_rate_limited():
                try:
                    _manager_metrics["secondary_requests"] += 1
                    t0 = time.perf_counter()
                    weather = await self.secondary.fetch_current_weather(lat, lon)
                    dur_ms = (time.perf_counter() - t0) * 1000.0
                    _manager_metrics["secondary_successes"] += 1
                    weather.source = "OPEN_METEO"
                    self._save_to_current_cache(key, weather)
                    logger.info(
                        "Weather Provider Fallback Success | provider=%s | coords=(%.2f, %.2f) | duration=%.1fms",
                        secondary_name, lat, lon, dur_ms
                    )
                    return weather
                except Exception as e:
                    _manager_metrics["secondary_failures"] += 1
                    logger.error(
                        "Secondary provider %s also failed for coords=(%.2f, %.2f): %s",
                        secondary_name, lat, lon, str(e)
                    )
            else:
                rem = self.secondary.get_cooldown_remaining()
                logger.warning(
                    "Secondary provider %s is also in active cooldown (%.1fs remaining).",
                    secondary_name, rem
                )

            # 5. Upstream exhausted: Fallback to Stale Cache
            stale_cached = self._get_stale_from_current_cache(key)
            if stale_cached is not None:
                return stale_cached

            # 6. Controlled UNAVAILABLE response
            _manager_metrics["unavailable_responses"] += 1
            min_cooldown = max(
                0.0,
                min(
                    self.primary.get_cooldown_remaining() or 60.0,
                    self.secondary.get_cooldown_remaining() or 60.0,
                )
            )
            logger.error(
                "All weather providers unavailable and no cache found for coords=(%.2f, %.2f). Serving controlled UNAVAILABLE.",
                lat, lon
            )
            return NormalizedCurrentWeather(
                temperature=None,
                feels_like=None,
                humidity=None,
                wind_speed=None,
                wind_direction=None,
                pressure=None,
                precipitation=None,
                cloud_cover=None,
                weather_code=None,
                condition="Unavailable",
                condition_description="Weather data temporarily unavailable from upstream providers",
                condition_icon="01d",
                provider="None",
                source="UNAVAILABLE",
                attribution="Meteorological data temporarily unavailable",
                is_available=False,
                cooldown_remaining_seconds=min_cooldown,
            )

    async def get_hourly_forecast(
        self, lat: float, lon: float, hours: int = 48
    ) -> List[NormalizedHourlyForecast]:
        """Retrieve multi-hour weather forecast via multi-provider failover chain."""
        key = f"{self.format_coord_key(lat, lon)}_{hours}h"
        now = time.monotonic()

        # Check hourly cache
        if key in _shared_hourly_cache:
            entry = _shared_hourly_cache[key]
            if now < entry[0]:
                return entry[3]

        # 1. Primary provider
        if not self.primary.is_rate_limited():
            try:
                forecast = await self.primary.fetch_hourly_forecast(lat, lon, hours=hours)
                if forecast:
                    _shared_hourly_cache[key] = (
                        now + self.cache_ttl_secs,
                        now + self.stale_ttl_secs,
                        now,
                        forecast,
                    )
                    return forecast
            except Exception as e:
                logger.warning("Primary provider hourly forecast failed: %s", str(e))

        # 2. Secondary provider
        if not self.secondary.is_rate_limited():
            try:
                forecast = await self.secondary.fetch_hourly_forecast(lat, lon, hours=hours)
                if forecast:
                    _shared_hourly_cache[key] = (
                        now + self.cache_ttl_secs,
                        now + self.stale_ttl_secs,
                        now,
                        forecast,
                    )
                    return forecast
            except Exception as e:
                logger.warning("Secondary provider hourly forecast failed: %s", str(e))

        # 3. Check stale hourly cache
        if key in _shared_hourly_cache:
            entry = _shared_hourly_cache[key]
            if now < entry[1]:
                return entry[3]

        return []
