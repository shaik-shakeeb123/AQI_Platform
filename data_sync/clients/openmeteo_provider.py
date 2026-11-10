from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

from api_layer.exceptions import ExternalAPIException
from api_layer.logging import get_logger
from data_sync.clients.base_weather_provider import BaseWeatherProvider
from data_sync.clients.openmeteo_weather_client import (
    OpenMeteoWeatherClient,
    is_rate_limited as om_is_rate_limited,
    get_cooldown_remaining as om_get_cooldown_remaining,
    set_cooldown as om_set_cooldown,
    get_weather_client_metrics as om_get_metrics,
    reset_weather_client_metrics as om_reset_metrics,
)
from data_sync.clients.weather_code_mapping import decode_weather_code
from data_sync.models.weather_models import (
    NormalizedCurrentWeather,
    NormalizedHourlyForecast,
)
from services.timezone_service import resolve_iana_timezone

logger = get_logger(__name__)


class OpenMeteoProvider(BaseWeatherProvider):
    """Adapter implementing BaseWeatherProvider for Open-Meteo Forecast API."""

    PROVIDER_NAME = "Open-Meteo"
    ATTRIBUTION = "Weather data by Open-Meteo.com"

    def __init__(self, client: Optional[OpenMeteoWeatherClient] = None) -> None:
        self.client = client or OpenMeteoWeatherClient()

    def get_provider_name(self) -> str:
        return self.PROVIDER_NAME

    def get_attribution(self) -> str:
        return self.ATTRIBUTION

    def is_rate_limited(self) -> bool:
        return om_is_rate_limited()

    def get_cooldown_remaining(self) -> float:
        return om_get_cooldown_remaining()

    def set_cooldown(self, seconds: float, reason: str = "HTTP 429 Rate Limit") -> None:
        om_set_cooldown(seconds, reason)

    def get_metrics(self) -> Dict[str, Any]:
        return om_get_metrics()

    def reset_metrics(self) -> None:
        om_reset_metrics()

    async def fetch_current_weather(
        self, lat: float, lon: float
    ) -> NormalizedCurrentWeather:
        """Fetch current weather from Open-Meteo and normalize to NormalizedCurrentWeather."""
        raw_data = await self.client.fetch_current_weather(lat, lon)
        current = raw_data.get("current", {})
        daily = raw_data.get("daily", {})

        weather_code = current.get("weather_code")
        decoded = decode_weather_code(weather_code)

        sunrise_iso = None
        sunset_iso = None
        sunrise_ts = None
        sunset_ts = None

        sunrises = daily.get("sunrise", [])
        if sunrises and sunrises[0]:
            sunrise_iso = sunrises[0]
            try:
                dt_sr = datetime.fromisoformat(sunrise_iso)
                sunrise_ts = int(dt_sr.timestamp())
            except Exception:
                pass

        sunsets = daily.get("sunset", [])
        if sunsets and sunsets[0]:
            sunset_iso = sunsets[0]
            try:
                dt_ss = datetime.fromisoformat(sunset_iso)
                sunset_ts = int(dt_ss.timestamp())
            except Exception:
                pass

        raw_time = current.get("time")
        recorded_at = None
        if raw_time:
            try:
                recorded_at = datetime.fromisoformat(raw_time.replace("Z", "+00:00"))
            except Exception:
                recorded_at = datetime.now(timezone.utc)
        else:
            recorded_at = datetime.now(timezone.utc)

        # Check source from client (e.g. if served from client stale cache or live)
        source = raw_data.get("source", "OPEN_METEO")
        if source == "LIVE":
            source = "OPEN_METEO"

        return NormalizedCurrentWeather(
            temperature=current.get("temperature_2m"),
            feels_like=current.get("apparent_temperature"),
            humidity=current.get("relative_humidity_2m"),
            wind_speed=current.get("wind_speed_10m"),
            wind_direction=current.get("wind_direction_10m"),
            pressure=current.get("surface_pressure"),
            precipitation=current.get("precipitation"),
            cloud_cover=current.get("cloud_cover"),
            weather_code=weather_code,
            condition=decoded.main if decoded else None,
            condition_description=decoded.description if decoded else None,
            condition_icon=decoded.icon if decoded else None,
            sunrise=sunrise_iso,
            sunset=sunset_iso,
            sunrise_timestamp=sunrise_ts,
            sunset_timestamp=sunset_ts,
            timezone=raw_data.get("timezone") or resolve_iana_timezone(lat, lon),
            recorded_at=recorded_at,
            provider=self.PROVIDER_NAME,
            source=source,
            attribution=self.ATTRIBUTION,
            is_available=raw_data.get("is_available", True),
            cached_at=raw_data.get("cached_at"),
            cooldown_remaining_seconds=raw_data.get("cooldown_remaining_seconds"),
            raw_data=raw_data,
        )

    async def fetch_hourly_forecast(
        self, lat: float, lon: float, hours: int = 48
    ) -> List[NormalizedHourlyForecast]:
        """Fetch hourly weather from Open-Meteo and normalize to NormalizedHourlyForecast."""
        forecast_days = max(2, (hours // 24) + 1)
        raw_data = await self.client.fetch_hourly_weather(lat, lon, forecast_days=forecast_days)
        hourly = raw_data.get("hourly", {})
        times = hourly.get("time", [])
        temps = hourly.get("temperature_2m", [])
        humids = hourly.get("relative_humidity_2m", [])
        winds = hourly.get("wind_speed_10m", [])
        wind_dirs = hourly.get("wind_direction_10m", [])
        precips = hourly.get("precipitation", [])
        pressures = hourly.get("surface_pressure", [])
        clouds = hourly.get("cloud_cover", [])
        wcodes = hourly.get("weather_code", [])

        forecast_list: List[NormalizedHourlyForecast] = []
        for i, t_str in enumerate(times[:hours]):
            try:
                dt = datetime.fromisoformat(t_str.replace("Z", "+00:00"))
            except Exception:
                continue

            w_code = wcodes[i] if i < len(wcodes) else None
            decoded = decode_weather_code(w_code) if w_code is not None else None

            forecast_list.append(
                NormalizedHourlyForecast(
                    timestamp=dt,
                    temperature=temps[i] if i < len(temps) else None,
                    humidity=humids[i] if i < len(humids) else None,
                    wind_speed=winds[i] if i < len(winds) else None,
                    wind_direction=wind_dirs[i] if i < len(wind_dirs) else None,
                    precipitation=precips[i] if i < len(precips) else None,
                    pressure=pressures[i] if i < len(pressures) else None,
                    cloud_cover=clouds[i] if i < len(clouds) else None,
                    condition=decoded.main if decoded else None,
                    weather_code=w_code,
                    provider=self.PROVIDER_NAME,
                )
            )

        return forecast_list
