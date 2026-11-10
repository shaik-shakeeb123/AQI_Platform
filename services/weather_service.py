from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from fastapi import HTTPException

from api_layer.logging import get_logger
from api_layer.api.schemas.aqi_endpoints import WeatherResponse
from data_sync.clients.nominatim_client import NominatimGeocoderClient
from services.weather_provider_manager import (
    WeatherProviderManager,
    clear_shared_weather_cache,
)
from services.timezone_service import resolve_iana_timezone

logger = get_logger(__name__)

_WEATHER_CACHE_MAX_SIZE = 1000
_WEATHER_CACHE_TTL_SECS = 600.0   # 10 minutes fresh
_WEATHER_STALE_TTL_SECS = 3600.0  # 1 hour stale retention

# City-keyed cache: city_key -> (expires_at, stale_until, created_at_iso, WeatherResponse)
_city_weather_cache: OrderedDict[str, tuple[float, float, str, WeatherResponse]] = OrderedDict()

# Concurrency locks partitioned by event loop for 100% lifecycle safety
_sharded_city_locks: list[asyncio.Lock] | None = None
_city_locks_loop_id: int | None = None

_cache_metrics = {
    "hit": 0,
    "miss": 0,
    "stale": 0,
    "eviction": 0,
}


def _get_city_lock(city_key: str) -> asyncio.Lock:
    global _sharded_city_locks, _city_locks_loop_id
    try:
        curr_loop = asyncio.get_running_loop()
        curr_id = id(curr_loop)
    except RuntimeError:
        curr_id = 0
    if _sharded_city_locks is None or _city_locks_loop_id != curr_id:
        _sharded_city_locks = [asyncio.Lock() for _ in range(256)]
        _city_locks_loop_id = curr_id
    return _sharded_city_locks[hash(city_key) % 256]


def clear_weather_service_cache() -> None:
    """Clear in-memory weather service cache and reset metrics (primarily for tests)."""
    global _sharded_city_locks, _city_locks_loop_id
    _city_weather_cache.clear()
    _sharded_city_locks = None
    _city_locks_loop_id = None
    _cache_metrics["hit"] = 0
    _cache_metrics["miss"] = 0
    _cache_metrics["stale"] = 0
    _cache_metrics["eviction"] = 0
    clear_shared_weather_cache()


class WeatherService:
    """Centralized service orchestrating current meteorological retrieval and hourly forecasting."""

    def __init__(self, provider_manager: Optional[WeatherProviderManager] = None) -> None:
        self.provider_manager = provider_manager or WeatherProviderManager()

    async def get_weather(self, city: str) -> WeatherResponse:
        """Geocode the city, retrieve weather from multi-provider manager, and build response."""
        logger.info("Retrieving weather for city=%s", city)
        city_key = city.strip().lower()
        city_lock = _get_city_lock(city_key)

        async with city_lock:
            # 1. Check City-Level Fresh Cache
            now = time.monotonic()
            if city_key in _city_weather_cache:
                entry = _city_weather_cache[city_key]
                expires_at = entry[0]
                cached_resp = entry[3]
                if now < expires_at:
                    _cache_metrics["hit"] += 1
                    _city_weather_cache.move_to_end(city_key)
                    logger.info("City weather cache HIT | city=%s | source=CACHE", city)
                    # Return clone with CACHE source tag
                    resp_dict = cached_resp.model_dump()
                    resp_dict["source"] = "CACHE"
                    return WeatherResponse(**resp_dict)

            # 2. Geocode City Coordinates
            _cache_metrics["miss"] += 1
            geo_details = await NominatimGeocoderClient.geocode_address_with_details(city, "")
            if not geo_details:
                # Check stale cache before raising 404
                if city_key in _city_weather_cache:
                    entry = _city_weather_cache[city_key]
                    if now < entry[1]:
                        _cache_metrics["stale"] += 1
                        _city_weather_cache.move_to_end(city_key)
                        resp_dict = entry[3].model_dump()
                        resp_dict["source"] = "STALE_CACHE"
                        resp_dict["is_available"] = True
                        return WeatherResponse(**resp_dict)

                logger.warning("Geocoding failed for weather query of city=%s", city)
                raise HTTPException(
                    status_code=404,
                    detail=f"City '{city}' could not be geocoded to valid coordinates."
                )

            lat = geo_details.latitude
            lon = geo_details.longitude
            country = geo_details.country
            country_code = geo_details.country_code

            # 3. Retrieve weather via Multi-Provider Manager
            weather = await self.provider_manager.get_current_weather(lat, lon)

            # 4. Resolve authoritative IANA timezone
            resolved_tz = (
                weather.timezone
                if (weather.timezone and weather.timezone != "UTC")
                else resolve_iana_timezone(lat, lon, country_code)
            )

            # 5. Construct WeatherResponse
            response = WeatherResponse(
                city=city,
                country=country,
                country_code=country_code,
                latitude=lat,
                longitude=lon,
                timezone=resolved_tz,
                temperature=weather.temperature,
                feels_like=weather.feels_like,
                humidity=weather.humidity,
                wind_speed=weather.wind_speed,
                wind_speed_unit="km/h",
                wind_direction=weather.wind_direction,
                pressure=weather.pressure,
                precipitation=weather.precipitation,
                weather_code=weather.weather_code,
                condition=weather.condition,
                condition_description=weather.condition_description,
                condition_icon=weather.condition_icon,
                sunrise=weather.sunrise,
                sunset=weather.sunset,
                sunrise_timestamp=weather.sunrise_timestamp,
                sunset_timestamp=weather.sunset_timestamp,
                provider=weather.provider,
                attribution=weather.attribution,
                source=weather.source,
                is_available=weather.is_available,
                cached_at=weather.cached_at,
                cooldown_remaining_seconds=weather.cooldown_remaining_seconds,
                raw_response=weather.raw_data,
            )

            # 5. Populate City Cache
            if weather.is_available:
                created_iso = datetime.now(timezone.utc).isoformat()
                _city_weather_cache[city_key] = (
                    now + _WEATHER_CACHE_TTL_SECS,
                    now + _WEATHER_STALE_TTL_SECS,
                    created_iso,
                    response,
                )
                if len(_city_weather_cache) > _WEATHER_CACHE_MAX_SIZE:
                    _city_weather_cache.popitem(last=False)
                    _cache_metrics["eviction"] += 1

            return response

    @classmethod
    async def fetch_hourly_forecast(
        cls, lat: float, lon: float
    ) -> Dict[tuple[int, int, int, int], Dict[str, Any]]:
        """Fetch 48-hour weather forecast indexed by (year, month, day, hour)."""
        forecast_map: Dict[tuple[int, int, int, int], Dict[str, Any]] = {}
        try:
            manager = WeatherProviderManager()
            forecast_items = await manager.get_hourly_forecast(lat, lon, hours=48)
            for item in forecast_items:
                ts = item.timestamp
                # Normalize timestamp to UTC key tuple
                if ts.tzinfo is not None:
                    ts_utc = ts.astimezone(timezone.utc)
                else:
                    ts_utc = ts
                key = (ts_utc.year, ts_utc.month, ts_utc.day, ts_utc.hour)
                forecast_map[key] = {
                    "temperature": item.temperature,
                    "humidity": item.humidity,
                    "wind_speed": item.wind_speed,
                    "wind_direction": item.wind_direction,
                    "precipitation": item.precipitation,
                    "pressure": item.pressure,
                    "cloud_cover": item.cloud_cover,
                }
        except Exception as e:
            logger.warning("Failed to fetch hourly forecast from WeatherProviderManager: %s", str(e))
        return forecast_map

    @classmethod
    async def fetch_current_weather(cls, lat: float, lon: float) -> dict:
        """Fetch current weather via provider manager returning legacy dictionary format."""
        manager = WeatherProviderManager()
        normalized = await manager.get_current_weather(lat, lon)
        return normalized.to_legacy_dict()
