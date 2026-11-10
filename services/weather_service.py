from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional
from fastapi import HTTPException

from api_layer.exceptions import ExternalAPIException
from api_layer.logging import get_logger
from api_layer.api.schemas.aqi_endpoints import WeatherResponse
from data_sync.clients.openmeteo_weather_client import (
    OpenMeteoWeatherClient,
    get_cooldown_remaining,
    is_rate_limited,
)
from data_sync.clients.weather_code_mapping import decode_weather_code

logger = get_logger(__name__)

_WEATHER_CACHE_MAX_SIZE = 1000
_WEATHER_CACHE_TTL_SECS = 600.0   # 10 minutes fresh
_WEATHER_STALE_TTL_SECS = 3600.0  # 1 hour stale retention

# cache stores: city_key -> (expires_at, stale_until, created_at_iso, WeatherResponse)
_weather_cache: OrderedDict[str, tuple[float, float, str, WeatherResponse]] = OrderedDict()
# 256 static locks for sharding to prevent lock leaks
_city_locks = [asyncio.Lock() for _ in range(256)]

_cache_metrics = {
    "hit": 0,
    "miss": 0,
    "stale": 0,
    "eviction": 0,
}

def clear_weather_service_cache() -> None:
    """Clear in-memory weather service cache and reset metrics (primarily for tests)."""
    _weather_cache.clear()
    _cache_metrics["hit"] = 0
    _cache_metrics["miss"] = 0
    _cache_metrics["stale"] = 0
    _cache_metrics["eviction"] = 0


def _get_city_lock(city_key: str) -> asyncio.Lock:
    return _city_locks[hash(city_key) % 256]


def _parse_iso_to_timestamp(iso_str: Optional[str], tz_str: Optional[str] = None) -> Optional[int]:
    """Convert an ISO 8601 datetime string to a Unix timestamp (seconds).

    Returns ``None`` when *iso_str* is ``None`` or cannot be parsed.
    """
    if not iso_str:
        return None
    try:
        dt = datetime.fromisoformat(iso_str)
        if tz_str:
            from zoneinfo import ZoneInfo
            dt = dt.replace(tzinfo=ZoneInfo(tz_str))
        return int(dt.timestamp())
    except (ValueError, TypeError, Exception) as e:
        logger.warning("Could not parse ISO timestamp %s with tz %s: %s", iso_str, tz_str, str(e))
        return None


class WeatherService:
    """Service orchestrating current weather condition retrieval and hourly meteorological forecasting."""

    def __init__(self) -> None:
        pass

    async def get_weather(self, city: str) -> WeatherResponse:
        """Geocode the city, call weather services, and build the weather response payload.

        Every value in the response originates from an authoritative data source:
        - Coordinates and country metadata from Nominatim
        - Meteorological data from Open-Meteo
        - Weather condition decoding via WMO weather code mapping
        """
        logger.info("Retrieving current weather for city=%s", city)
        
        city_key = city.strip().lower()
        city_lock = _get_city_lock(city_key)
        
        async with city_lock:
            # 1. Check Cache
            now = time.monotonic()
            if city_key in _weather_cache:
                entry = _weather_cache[city_key]
                expires_at = entry[0]
                cached_resp = entry[-1]
                if now < expires_at:
                    _cache_metrics["hit"] += 1
                    logger.info("Weather cache HIT for city=%s | source=CACHE | Metrics: %s", city, _cache_metrics)
                    # Move to end to maintain LRU
                    _weather_cache.move_to_end(city_key)
                    return cached_resp
            
            _cache_metrics["miss"] += 1
            logger.info("Weather cache MISS for city=%s | Metrics: %s", city, _cache_metrics)

            from data_sync.clients.nominatim_client import NominatimGeocoderClient

            # ── Geocode (with rich metadata) ──────────────────────────────────
            geo = await NominatimGeocoderClient.geocode_address_with_details(city, "")
            if not geo:
                logger.warning("Geocoding failed for weather query of city=%s", city)
                raise HTTPException(
                    status_code=404,
                    detail=f"Location geocoding failed for city '{city}'.",
                )

        lat, lon = geo.latitude, geo.longitude
        logger.info(
            "Resolved weather city=%s to coords=(%s, %s) country=%s. Querying Open-Meteo Weather API...",
            city, lat, lon, geo.country_code,
        )

        # ── Fetch weather from Open-Meteo ─────────────────────────────────
        try:
            client = OpenMeteoWeatherClient()
            weather_data = await client.fetch_current_weather(lat, lon)
        except ExternalAPIException as e:
            now = time.monotonic()
            # Stale-While-Revalidate: If we have an expired cache, serve it instead of failing
            if city_key in _weather_cache:
                entry = _weather_cache[city_key]
                stale_until = entry[1]
                created_at_iso = entry[2] if len(entry) >= 4 else None
                stale_resp = entry[-1]
                if now < stale_until:
                    _cache_metrics["stale"] += 1
                    logger.warning(
                        "Open-Meteo API failed (status=%s). Serving STALE cache for city=%s (cached_at=%s) | Metrics: %s", 
                        e.upstream_status, city, created_at_iso, _cache_metrics
                    )
                    _weather_cache.move_to_end(city_key)
                    return stale_resp.model_copy(
                        update={
                            "source": "STALE_CACHE",
                            "is_available": True,
                            "cached_at": created_at_iso,
                            "cooldown_remaining_seconds": round(get_cooldown_remaining(), 1),
                        }
                    )
                else:
                    del _weather_cache[city_key]

            # If no fresh or stale cache exists, return controlled UNAVAILABLE response
            cooldown_rem = get_cooldown_remaining()
            logger.warning(
                "Open-Meteo rate limit active (cooldown=%.1fs). No cache for city=%s. Returning controlled UNAVAILABLE response.",
                cooldown_rem, city
            )
            return WeatherResponse(
                city=city,
                country=geo.country,
                country_code=geo.country_code,
                latitude=lat,
                longitude=lon,
                timezone=None,
                temperature=None,
                feels_like=None,
                humidity=None,
                wind_speed=None,
                wind_speed_unit="km/h",
                wind_direction=None,
                pressure=None,
                precipitation=None,
                weather_code=None,
                condition="Unavailable",
                condition_description="Weather data temporarily unavailable (upstream rate limit active)",
                condition_icon=None,
                sunrise=None,
                sunset=None,
                sunrise_timestamp=None,
                sunset_timestamp=None,
                provider="Open-Meteo",
                source="UNAVAILABLE",
                is_available=False,
                cached_at=None,
                cooldown_remaining_seconds=round(cooldown_rem, 1),
                raw_response={"error": str(e.detail), "upstream_status": e.upstream_status or 429},
            )
        except Exception as e:
            logger.error("Unexpected error fetching weather for coords=(%s, %s): %s", lat, lon, e)
            now = time.monotonic()
            if city_key in _weather_cache:
                entry = _weather_cache[city_key]
                stale_until = entry[1]
                created_at_iso = entry[2] if len(entry) >= 4 else None
                stale_resp = entry[-1]
                if now < stale_until:
                    _cache_metrics["stale"] += 1
                    logger.warning("Serving STALE cache after unexpected error for city=%s", city)
                    return stale_resp.model_copy(
                        update={
                            "source": "STALE_CACHE",
                            "is_available": True,
                            "cached_at": created_at_iso,
                        }
                    )
            return WeatherResponse(
                city=city,
                country=geo.country,
                country_code=geo.country_code,
                latitude=lat,
                longitude=lon,
                timezone=None,
                temperature=None,
                feels_like=None,
                humidity=None,
                wind_speed=None,
                wind_speed_unit="km/h",
                wind_direction=None,
                pressure=None,
                precipitation=None,
                weather_code=None,
                condition="Unavailable",
                condition_description="Weather data temporarily unavailable",
                condition_icon=None,
                sunrise=None,
                sunset=None,
                sunrise_timestamp=None,
                sunset_timestamp=None,
                provider="Open-Meteo",
                source="UNAVAILABLE",
                is_available=False,
                cached_at=None,
                cooldown_remaining_seconds=round(get_cooldown_remaining(), 1),
                raw_response={"error": str(e)},
            )

        if not weather_data or "current" not in weather_data:
            logger.warning("Empty weather data block returned by Open-Meteo for coords=(%s, %s)", lat, lon)
            return WeatherResponse(
                city=city,
                country=geo.country,
                country_code=geo.country_code,
                latitude=lat,
                longitude=lon,
                timezone=None,
                temperature=None,
                feels_like=None,
                humidity=None,
                wind_speed=None,
                wind_speed_unit="km/h",
                wind_direction=None,
                pressure=None,
                precipitation=None,
                weather_code=None,
                condition="Unavailable",
                condition_description="Weather data unavailable from provider",
                condition_icon=None,
                sunrise=None,
                sunset=None,
                sunrise_timestamp=None,
                sunset_timestamp=None,
                provider="Open-Meteo",
                source="UNAVAILABLE",
                is_available=False,
                cached_at=None,
                cooldown_remaining_seconds=None,
                raw_response={},
            )

        current = weather_data["current"]
        daily = weather_data.get("daily", {})

        # ── Weather condition decoding ────────────────────────────────────
        weather_code = current.get("weather_code")
        decoded = decode_weather_code(weather_code)

        # ── Sunrise / Sunset ──────────────────────────────────────────────
        sunrise_str: Optional[str] = None
        sunset_str: Optional[str] = None
        sunrise_list = daily.get("sunrise", [])
        sunset_list = daily.get("sunset", [])
        if sunrise_list:
            sunrise_str = sunrise_list[0]
        if sunset_list:
            sunset_str = sunset_list[0]

        # ── Timezone ──────────────────────────────────────────────────────
        timezone_str = weather_data.get("timezone")
        now_mono = time.monotonic()
        created_at_iso = datetime.now(timezone.utc).isoformat()

        response = WeatherResponse(
            # Location
            city=city,
            country=geo.country,
            country_code=geo.country_code,
            latitude=lat,
            longitude=lon,
            timezone=timezone_str,
            # Core meteorological
            temperature=current.get("temperature_2m"),
            feels_like=current.get("apparent_temperature"),
            humidity=current.get("relative_humidity_2m"),
            wind_speed=current.get("wind_speed_10m"),
            wind_speed_unit="km/h",
            wind_direction=current.get("wind_direction_10m"),
            pressure=current.get("surface_pressure"),
            precipitation=current.get("precipitation"),
            # Weather condition
            weather_code=weather_code,
            condition=decoded.main,
            condition_description=decoded.description,
            condition_icon=decoded.icon,
            # Solar
            sunrise=sunrise_str,
            sunset=sunset_str,
            sunrise_timestamp=_parse_iso_to_timestamp(sunrise_str, timezone_str),
            sunset_timestamp=_parse_iso_to_timestamp(sunset_str, timezone_str),
            # Provider
            provider="Open-Meteo",
            source="LIVE",
            is_available=True,
            cached_at=created_at_iso,
            cooldown_remaining_seconds=None,
            # Raw (for debugging)
            raw_response=weather_data,
        )
        
        # 2. Update Cache & Evict if necessary
        _weather_cache[city_key] = (
            now_mono + _WEATHER_CACHE_TTL_SECS,
            now_mono + _WEATHER_STALE_TTL_SECS,
            created_at_iso,
            response,
        )
        if len(_weather_cache) > _WEATHER_CACHE_MAX_SIZE:
            _weather_cache.popitem(last=False)
            _cache_metrics["eviction"] += 1
            
        return response

    @staticmethod
    async def fetch_hourly_forecast(lat: float, lon: float) -> Dict[tuple[int, int, int, int], Dict[str, Any]]:
        """Fetch 2 days of hourly weather forecast from Open-Meteo and index it by (year, month, day, hour)."""
        forecast_map: Dict[tuple[int, int, int, int], Dict[str, Any]] = {}
        try:
            client = OpenMeteoWeatherClient()
            forecast_data = await client.fetch_hourly_weather(lat, lon, forecast_days=2)
            if forecast_data and "hourly" in forecast_data:
                hourly = forecast_data["hourly"]
                times = hourly.get("time", [])
                temps = hourly.get("temperature_2m", [])
                humids = hourly.get("relative_humidity_2m", [])
                winds = hourly.get("wind_speed_10m", [])
                wind_dirs = hourly.get("wind_direction_10m", [])
                precips = hourly.get("precipitation", [])
                pressures = hourly.get("surface_pressure", [])
                clouds = hourly.get("cloud_cover", [])

                utc_offset = forecast_data.get("utc_offset_seconds", 0)

                for i, t_str in enumerate(times):
                    try:
                        dt_local = datetime.fromisoformat(t_str.replace("Z", ""))
                        dt_utc = dt_local - timedelta(seconds=utc_offset)
                        key = (dt_utc.year, dt_utc.month, dt_utc.day, dt_utc.hour)
                        forecast_map[key] = {
                            "temperature": temps[i] if i < len(temps) else None,
                            "humidity": humids[i] if i < len(humids) else None,
                            "wind_speed": winds[i] if i < len(winds) else None,
                            "wind_direction": wind_dirs[i] if i < len(wind_dirs) else None,
                            "precipitation": precips[i] if i < len(precips) else None,
                            "pressure": pressures[i] if i < len(pressures) else None,
                            "cloud_cover": clouds[i] if i < len(clouds) else None,
                        }
                    except Exception as parse_ex:
                        logger.warning("Error parsing forecast time entry '%s': %s", t_str, str(parse_ex))
        except Exception as api_err:
            logger.warning("Failed to fetch hourly forecast from Open-Meteo: %s", str(api_err))
        return forecast_map
