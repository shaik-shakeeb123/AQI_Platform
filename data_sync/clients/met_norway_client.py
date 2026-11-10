from __future__ import annotations

import asyncio
import email.utils
import random
import time
from datetime import datetime, timezone, timedelta
from typing import Optional, Any, Dict, List, Tuple
import httpx

from api_layer.config import get_settings
from api_layer.exceptions import ExternalAPIException
from api_layer.logging import get_logger
from data_sync.clients.base_weather_provider import BaseWeatherProvider
from data_sync.clients.met_norway_symbol_mapping import decode_met_norway_symbol
from data_sync.models.weather_models import (
    NormalizedCurrentWeather,
    NormalizedHourlyForecast,
    calculate_apparent_temperature,
    calculate_solar_times,
)
from services.timezone_service import resolve_iana_timezone

logger = get_logger(__name__)

_client: httpx.AsyncClient | None = None
_client_loop_id: int | None = None

# Retry configuration for transient errors
_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 1.0
_RETRY_MAX_DELAY = 16.0
_RETRYABLE_STATUSES = {500, 502, 503, 504}
_MAX_COOLDOWN_CAP = 86400.0  # 24 hours cap

# Module-level state for MET Norway provider
_cooldown_until: float = 0.0
_last_modified_store: dict[str, str] = {}  # coord_key -> Last-Modified header value
_cached_raw_store: dict[str, dict] = {}    # coord_key -> raw GeoJSON response for 304 re-use

_provider_metrics: dict[str, Any] = {
    "upstream_requests": 0,
    "success_requests": 0,
    "failed_requests": 0,
    "rate_limit_hits": 0,
    "cache_304_hits": 0,
    "suppressed_requests": 0,
    "last_cooldown_reason": None,
    "last_retry_after": None,
}


def clear_met_norway_state() -> None:
    """Clear MET Norway cooldown, conditional headers, cache, and HTTP client (for tests)."""
    global _cooldown_until, _client, _client_loop_id
    _cooldown_until = 0.0
    _last_modified_store.clear()
    _cached_raw_store.clear()
    _client = None
    _client_loop_id = None
    _provider_metrics["upstream_requests"] = 0
    _provider_metrics["success_requests"] = 0
    _provider_metrics["failed_requests"] = 0
    _provider_metrics["rate_limit_hits"] = 0
    _provider_metrics["cache_304_hits"] = 0
    _provider_metrics["suppressed_requests"] = 0
    _provider_metrics["last_cooldown_reason"] = None
    _provider_metrics["last_retry_after"] = None


def _parse_retry_after(header_val: Any, default: float = 60.0) -> float:
    """Parse Retry-After header supporting both delay-seconds and HTTP-date (RFC 7231)."""
    if not header_val:
        return default
    header_str = str(header_val).strip()
    try:
        val = float(header_str)
        return min(max(1.0, val), _MAX_COOLDOWN_CAP)
    except (ValueError, TypeError):
        pass
    try:
        dt = email.utils.parsedate_to_datetime(header_str)
        if dt is not None:
            now = datetime.now(timezone.utc)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            diff = (dt - now).total_seconds()
            return min(max(1.0, diff), _MAX_COOLDOWN_CAP)
    except Exception:
        pass
    return default


class MetNorwayClient(BaseWeatherProvider):
    """Production-grade client for MET Norway Locationforecast 2.0 API.
    
    Adheres strictly to MET Norway Terms of Service:
    - Descriptive User-Agent identification
    - Respects caching and conditional If-Modified-Since requests
    - Truncates coordinates to 4 decimals to maximize upstream cache efficiency
    - Converts wind speed from m/s to km/h
    - Provides NLOD / CC BY 4.0 compliant attribution
    """

    PROVIDER_NAME = "MET Norway"
    ATTRIBUTION = "Data from MET Norway (api.met.no)"

    def __init__(
        self,
        base_url: Optional[str] = None,
        user_agent: Optional[str] = None,
        timeout: float = 10.0,
    ) -> None:
        settings = get_settings()
        self.base_url = (base_url or getattr(settings, "MET_NORWAY_BASE_URL", "https://api.met.no/weatherapi/locationforecast/2.0")).rstrip("/")
        self.user_agent = user_agent or getattr(
            settings,
            "MET_NORWAY_USER_AGENT",
            "AQIPlatform/1.0 (https://github.com/shaikshakeeb/AQI_Platform_V01, contact@aqi-platform.com)"
        )
        self.timeout = timeout

        # Strict User-Agent validation
        if not self.user_agent or "python" in self.user_agent.lower() or "curl" in self.user_agent.lower():
            logger.warning(
                "MET Norway requires a descriptive User-Agent with contact details. Currently using: %s",
                self.user_agent
            )

    def get_provider_name(self) -> str:
        return self.PROVIDER_NAME

    def get_attribution(self) -> str:
        return self.ATTRIBUTION

    def is_rate_limited(self) -> bool:
        return time.monotonic() < _cooldown_until

    def get_cooldown_remaining(self) -> float:
        return max(0.0, _cooldown_until - time.monotonic())

    def set_cooldown(self, seconds: float, reason: str = "HTTP 429 Rate Limit") -> None:
        global _cooldown_until
        try:
            sec = float(seconds)
            if sec <= 0.0:
                sec = 60.0
            elif sec > _MAX_COOLDOWN_CAP:
                sec = _MAX_COOLDOWN_CAP
        except (ValueError, TypeError):
            sec = 60.0

        new_until = time.monotonic() + sec
        if new_until > _cooldown_until:
            _cooldown_until = new_until
            _provider_metrics["last_cooldown_reason"] = reason
            _provider_metrics["last_retry_after"] = sec
            logger.warning(
                "MET Norway cooldown active for %.1fs (until %s). Reason: %s",
                sec, new_until, reason
            )

    def get_metrics(self) -> Dict[str, Any]:
        return dict(_provider_metrics)

    def reset_metrics(self) -> None:
        _provider_metrics["upstream_requests"] = 0
        _provider_metrics["success_requests"] = 0
        _provider_metrics["failed_requests"] = 0
        _provider_metrics["rate_limit_hits"] = 0
        _provider_metrics["cache_304_hits"] = 0
        _provider_metrics["suppressed_requests"] = 0
        _provider_metrics["last_cooldown_reason"] = None
        _provider_metrics["last_retry_after"] = None

    def reset_cooldown(self) -> None:
        global _cooldown_until
        _cooldown_until = 0.0

    @classmethod
    def _get_http_client(cls, timeout: float = 10.0) -> httpx.AsyncClient:
        global _client, _client_loop_id
        try:
            curr_loop = asyncio.get_running_loop()
            curr_id = id(curr_loop)
        except RuntimeError:
            curr_id = 0
        if _client is None or _client.is_closed or _client_loop_id != curr_id:
            _client = httpx.AsyncClient(
                timeout=timeout,
                headers={"Accept-Encoding": "gzip, deflate"}
            )
            _client_loop_id = curr_id
        return _client

    @classmethod
    async def close_client(cls) -> None:
        global _client
        if _client is not None and not _client.is_closed:
            await _client.aclose()
            _client = None

    def _format_coords(self, lat: float, lon: float) -> Tuple[str, str, str]:
        """Truncate coordinates to 4 decimal places as requested by MET Norway."""
        lat_str = f"{round(lat, 4):.4f}"
        lon_str = f"{round(lon, 4):.4f}"
        coord_key = f"{lat_str}_{lon_str}"
        return lat_str, lon_str, coord_key

    async def _execute_request(self, lat: float, lon: float) -> dict:
        """Execute request to MET Norway Locationforecast compact endpoint with retries and 304 handling."""
        if self.is_rate_limited():
            _provider_metrics["suppressed_requests"] += 1
            rem = self.get_cooldown_remaining()
            raise ExternalAPIException(
                detail=f"MET Norway API: Cooldown active ({rem:.1f}s remaining). Request suppressed.",
                error_code="MET_NORWAY_COOLDOWN_ACTIVE",
                status_code=502,
                upstream_status=429
            )

        lat_str, lon_str, coord_key = self._format_coords(lat, lon)
        url = f"{self.base_url}/compact"
        params = {"lat": lat_str, "lon": lon_str}

        headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/json",
        }
        if coord_key in _last_modified_store:
            headers["If-Modified-Since"] = _last_modified_store[coord_key]

        client = self._get_http_client(self.timeout)
        attempt = 0

        while attempt <= _MAX_RETRIES:
            attempt += 1
            try:
                _provider_metrics["upstream_requests"] += 1
                logger.info(
                    "MET Norway HTTP Request | attempt=%d/%d | coords=(%s, %s)",
                    attempt, _MAX_RETRIES + 1, lat_str, lon_str
                )
                start_t = time.perf_counter()
                response = await client.get(url, params=params, headers=headers)
                latency_ms = (time.perf_counter() - start_t) * 1000.0

                # 1. Handle HTTP 304 Not Modified
                if response.status_code == 304:
                    _provider_metrics["cache_304_hits"] += 1
                    _provider_metrics["success_requests"] += 1
                    logger.info("MET Norway 304 Not Modified | key=%s | latency=%.1fms", coord_key, latency_ms)
                    if coord_key in _cached_raw_store:
                        return _cached_raw_store[coord_key]
                    # If somehow cached payload missing, re-fetch without If-Modified-Since
                    headers.pop("If-Modified-Since", None)
                    continue

                # 2. Handle HTTP 429 Too Many Requests
                if response.status_code == 429:
                    _provider_metrics["rate_limit_hits"] += 1
                    _provider_metrics["failed_requests"] += 1
                    retry_after_hdr = response.headers.get("Retry-After")
                    cooldown_sec = _parse_retry_after(retry_after_hdr, default=60.0)
                    self.set_cooldown(cooldown_sec, reason=f"HTTP 429 Rate Limit (Retry-After: {retry_after_hdr})")
                    raise ExternalAPIException(
                        detail=f"MET Norway API: HTTP 429 Too Many Requests. Cooldown engaged for {cooldown_sec:.1f}s.",
                        error_code="MET_NORWAY_RATE_LIMIT",
                        status_code=502,
                        upstream_status=429
                    )

                # 3. Handle Transient 5xx status codes
                if response.status_code in _RETRYABLE_STATUSES:
                    if attempt <= _MAX_RETRIES:
                        backoff = min(_RETRY_BASE_DELAY * (2 ** (attempt - 1)) + random.uniform(0.1, 0.5), _RETRY_MAX_DELAY)
                        logger.warning(
                            "MET Norway transient HTTP %d | coords=(%s, %s) | Retrying in %.2fs (attempt %d/%d)",
                            response.status_code, lat_str, lon_str, backoff, attempt, _MAX_RETRIES
                        )
                        await asyncio.sleep(backoff)
                        continue
                    else:
                        _provider_metrics["failed_requests"] += 1
                        raise ExternalAPIException(
                            detail=f"MET Norway API: HTTP {response.status_code} after {_MAX_RETRIES + 1} attempts.",
                            error_code="MET_NORWAY_SERVER_ERROR",
                            status_code=502,
                            upstream_status=response.status_code
                        )

                # 4. Handle other non-200 status codes (400, 403, 404, etc.)
                if response.status_code != 200:
                    _provider_metrics["failed_requests"] += 1
                    raise ExternalAPIException(
                        detail=f"MET Norway API returned HTTP {response.status_code}: {response.text[:200]}",
                        error_code="MET_NORWAY_API_ERROR",
                        status_code=502,
                        upstream_status=response.status_code
                    )

                # 5. Success 200 OK
                data = response.json()
                _provider_metrics["success_requests"] += 1

                # Update conditional request cache
                last_mod = response.headers.get("last-modified")
                if last_mod:
                    _last_modified_store[coord_key] = last_mod
                _cached_raw_store[coord_key] = data

                logger.info(
                    "MET Norway HTTP 200 OK | coords=(%s, %s) | latency=%.1fms",
                    lat_str, lon_str, latency_ms
                )
                return data

            except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout) as e:
                if attempt <= _MAX_RETRIES:
                    backoff = min(_RETRY_BASE_DELAY * (2 ** (attempt - 1)) + random.uniform(0.1, 0.5), _RETRY_MAX_DELAY)
                    logger.warning("MET Norway timeout: %s | Retrying in %.2fs", str(e), backoff)
                    await asyncio.sleep(backoff)
                    continue
                _provider_metrics["failed_requests"] += 1
                raise ExternalAPIException(
                    detail=f"MET Norway API request timed out after {_MAX_RETRIES + 1} attempts.",
                    error_code="MET_NORWAY_TIMEOUT",
                    status_code=504,
                    upstream_status=504
                ) from e

            except httpx.NetworkError as e:
                if attempt <= _MAX_RETRIES:
                    backoff = min(_RETRY_BASE_DELAY * (2 ** (attempt - 1)) + random.uniform(0.1, 0.5), _RETRY_MAX_DELAY)
                    logger.warning("MET Norway network error: %s | Retrying in %.2fs", str(e), backoff)
                    await asyncio.sleep(backoff)
                    continue
                _provider_metrics["failed_requests"] += 1
                raise ExternalAPIException(
                    detail=f"MET Norway API network failure: {str(e)}",
                    error_code="MET_NORWAY_NETWORK_ERROR",
                    status_code=502,
                    upstream_status=502
                ) from e

        _provider_metrics["failed_requests"] += 1
        raise ExternalAPIException(
            detail="MET Norway API query exhausted maximum retry attempts.",
            error_code="MET_NORWAY_MAX_RETRIES_EXCEEDED",
            status_code=502,
            upstream_status=502
        )

    def _parse_current(self, data: dict, lat: float, lon: float) -> NormalizedCurrentWeather:
        """Parse raw GeoJSON into NormalizedCurrentWeather."""
        properties = data.get("properties", {})
        timeseries = properties.get("timeseries", [])
        if not timeseries:
            raise ValueError("MET Norway payload contains no timeseries entries")

        current_entry = timeseries[0]
        data_block = current_entry.get("data", {})
        instant_details = data_block.get("instant", {}).get("details", {})

        # Air temperature (°C)
        temp_c = instant_details.get("air_temperature")

        # Relative humidity (%)
        humidity = instant_details.get("relative_humidity")

        # Pressure (hPa)
        pressure = instant_details.get("air_pressure_at_sea_level")

        # Wind speed: converted from m/s to km/h (1 m/s = 3.6 km/h)
        wind_speed_ms = instant_details.get("wind_speed")
        wind_speed_kmh = round(wind_speed_ms * 3.6, 1) if wind_speed_ms is not None else None

        # Wind direction (0-360°)
        wind_direction = instant_details.get("wind_from_direction")

        # Cloud cover (%)
        cloud_cover = instant_details.get("cloud_area_fraction")

        # Apparent temperature calculation
        feels_like = None
        if temp_c is not None and humidity is not None:
            feels_like = calculate_apparent_temperature(
                temp_c, humidity, wind_speed_ms or 0.0
            )

        # Weather condition symbol and precipitation
        next_1h = data_block.get("next_1_hours", {})
        next_6h = data_block.get("next_6_hours", {})

        symbol_code = next_1h.get("summary", {}).get("symbol_code") or next_6h.get("summary", {}).get("symbol_code")
        precipitation = (
            next_1h.get("details", {}).get("precipitation_amount")
            if next_1h
            else next_6h.get("details", {}).get("precipitation_amount")
        )

        # Timestamp parsing
        raw_time = current_entry.get("time")
        recorded_at = None
        if raw_time:
            try:
                recorded_at = datetime.fromisoformat(raw_time.replace("Z", "+00:00"))
            except Exception:
                recorded_at = datetime.now(timezone.utc)
        else:
            recorded_at = datetime.now(timezone.utc)

        # Solar times
        sunrise_dt, sunset_dt = calculate_solar_times(lat, lon, recorded_at)
        sunrise_iso = sunrise_dt.isoformat() if sunrise_dt else None
        sunset_iso = sunset_dt.isoformat() if sunset_dt else None
        sunrise_ts = int(sunrise_dt.timestamp()) if sunrise_dt else None
        sunset_ts = int(sunset_dt.timestamp()) if sunset_dt else None

        # Daytime check for icon
        is_daytime = True
        if sunrise_ts and sunset_ts and recorded_at:
            curr_ts = int(recorded_at.timestamp())
            is_daytime = sunrise_ts <= curr_ts < sunset_ts

        # Decode symbol
        condition, condition_desc, condition_icon, wmo_code = decode_met_norway_symbol(
            symbol_code, is_daytime=is_daytime
        )

        iana_tz = resolve_iana_timezone(lat, lon)

        return NormalizedCurrentWeather(
            temperature=temp_c,
            feels_like=feels_like,
            humidity=humidity,
            wind_speed=wind_speed_kmh,
            wind_direction=wind_direction,
            pressure=pressure,
            precipitation=precipitation,
            cloud_cover=cloud_cover,
            weather_code=wmo_code,
            condition=condition,
            condition_description=condition_desc,
            condition_icon=condition_icon,
            sunrise=sunrise_iso,
            sunset=sunset_iso,
            sunrise_timestamp=sunrise_ts,
            sunset_timestamp=sunset_ts,
            timezone=iana_tz,
            recorded_at=recorded_at,
            provider=self.PROVIDER_NAME,
            source="MET_NORWAY",
            attribution=self.ATTRIBUTION,
            is_available=True,
            raw_data=data,
        )

    def _parse_hourly(
        self, data: dict, hours: int = 48
    ) -> List[NormalizedHourlyForecast]:
        """Parse raw GeoJSON into a list of NormalizedHourlyForecast entries."""
        properties = data.get("properties", {})
        timeseries = properties.get("timeseries", [])
        forecast_list: List[NormalizedHourlyForecast] = []

        for entry in timeseries[:hours]:
            time_str = entry.get("time")
            if not time_str:
                continue
            try:
                dt = datetime.fromisoformat(time_str.replace("Z", "+00:00"))
            except Exception:
                continue

            data_block = entry.get("data", {})
            instant_details = data_block.get("instant", {}).get("details", {})
            next_1h = data_block.get("next_1_hours", {})

            temp_c = instant_details.get("air_temperature")
            humidity = instant_details.get("relative_humidity")
            pressure = instant_details.get("air_pressure_at_sea_level")
            wind_speed_ms = instant_details.get("wind_speed")
            wind_speed_kmh = round(wind_speed_ms * 3.6, 1) if wind_speed_ms is not None else None
            wind_direction = instant_details.get("wind_from_direction")
            cloud_cover = instant_details.get("cloud_area_fraction")

            precip = next_1h.get("details", {}).get("precipitation_amount")
            symbol_code = next_1h.get("summary", {}).get("symbol_code")
            condition, _, _, wmo = decode_met_norway_symbol(symbol_code)

            forecast_list.append(
                NormalizedHourlyForecast(
                    timestamp=dt,
                    temperature=temp_c,
                    humidity=humidity,
                    wind_speed=wind_speed_kmh,
                    wind_direction=wind_direction,
                    precipitation=precip,
                    pressure=pressure,
                    cloud_cover=cloud_cover,
                    condition=condition,
                    weather_code=wmo,
                    provider=self.PROVIDER_NAME,
                )
            )

        return forecast_list

    async def fetch_current_weather(
        self, lat: float, lon: float
    ) -> NormalizedCurrentWeather:
        """Fetch current weather observations from MET Norway and return normalized model."""
        raw_data = await self._execute_request(lat, lon)
        return self._parse_current(raw_data, lat, lon)

    async def fetch_hourly_forecast(
        self, lat: float, lon: float, hours: int = 48
    ) -> List[NormalizedHourlyForecast]:
        """Fetch hourly weather forecast from MET Norway and return normalized entries."""
        raw_data = await self._execute_request(lat, lon)
        return self._parse_hourly(raw_data, hours=hours)
