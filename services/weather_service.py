from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from datetime import datetime, timedelta
from typing import Any, Dict, Optional
from fastapi import HTTPException

from api_layer.exceptions import ExternalAPIException
from api_layer.logging import get_logger
from api_layer.api.schemas.aqi_endpoints import WeatherResponse
from data_sync.clients.openmeteo_weather_client import OpenMeteoWeatherClient
from data_sync.clients.weather_code_mapping import decode_weather_code

logger = get_logger(__name__)

_WEATHER_CACHE_MAX_SIZE = 1000
_WEATHER_CACHE_TTL_SECS = 600  # 10 minutes

# cache stores: city_key -> (expires_at, WeatherResponse)
_weather_cache: OrderedDict[str, tuple[float, WeatherResponse]] = OrderedDict()
# 256 static locks for sharding to prevent lock leaks
_city_locks = [asyncio.Lock() for _ in range(256)]

_cache_metrics = {
    "hit": 0,
    "miss": 0,
    "stale": 0,
    "eviction": 0,
}

def _get_city_lock(city_key: str) -> asyncio.Lock:
    return _city_locks[hash(city_key) % 256]


def _parse_iso_to_timestamp(iso_str: Optional[str]) -> Optional[int]:
    """Convert an ISO 8601 datetime string to a Unix timestamp (seconds).

    Returns ``None`` when *iso_str* is ``None`` or cannot be parsed.
    """
    if not iso_str:
        return None
    try:
        dt = datetime.fromisoformat(iso_str)
        return int(dt.timestamp())
    except (ValueError, TypeError):
        logger.warning("Could not parse ISO timestamp: %s", iso_str)
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
            if city_key in _weather_cache:
                expires_at, cached_resp = _weather_cache[city_key]
                if time.monotonic() < expires_at:
                    _cache_metrics["hit"] += 1
                    logger.info("Weather cache HIT for city=%s | Metrics: %s", city, _cache_metrics)
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
            # Stale-While-Revalidate: If we have an expired cache, serve it instead of failing
            if city_key in _weather_cache:
                _cache_metrics["stale"] += 1
                logger.warning(
                    "Open-Meteo API failed (status=%s). Serving STALE cache for city=%s | Metrics: %s", 
                    e.upstream_status, city, _cache_metrics
                )
                _, stale_resp = _weather_cache[city_key]
                return stale_resp
            logger.error("Open-Meteo Weather API request failed for coords=(%s, %s): %s", lat, lon, e.detail)
            # Re-raise to preserve the upstream_status formatting in the JSON response
            raise e
        except Exception as e:
            logger.error("Unexpected error fetching weather for coords=(%s, %s): %s", lat, lon, e)
            raise HTTPException(
                status_code=502,
                detail=f"Failed to fetch weather data for city '{city}' from Open-Meteo: {str(e)}",
            )

        if not weather_data or "current" not in weather_data:
            logger.warning("Empty weather data block returned by Open-Meteo for coords=(%s, %s)", lat, lon)
            raise HTTPException(
                status_code=404,
                detail=f"Open-Meteo weather response for city '{city}' was empty.",
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
        timezone = weather_data.get("timezone")

        response = WeatherResponse(
            # Location
            city=city,
            country=geo.country,
            country_code=geo.country_code,
            latitude=lat,
            longitude=lon,
            timezone=timezone,
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
            sunrise_timestamp=_parse_iso_to_timestamp(sunrise_str),
            sunset_timestamp=_parse_iso_to_timestamp(sunset_str),
            # Provider
            provider="Open-Meteo",
            # Raw (for debugging)
            raw_response=weather_data,
        )
        
        # 2. Update Cache & Evict if necessary
        _weather_cache[city_key] = (time.monotonic() + _WEATHER_CACHE_TTL_SECS, response)
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
