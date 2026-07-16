from __future__ import annotations

import asyncio
import random
import httpx
from typing import Optional

from api_layer.config import get_settings
from api_layer.exceptions import ExternalAPIException
from api_layer.logging import get_logger

logger = get_logger(__name__)

_client: httpx.AsyncClient | None = None

# Retry configuration for transient errors.
_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 1.0
_RETRY_MAX_DELAY = 16.0
_RETRYABLE_STATUSES = {429, 500, 502, 503, 504}


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(timeout=30.0)
    return _client


async def _get_with_retry(url: str, params: dict, *, error_code: str, label: str) -> dict:
    """GET *url* with exponential back-off + jitter on transient failures."""
    last_exc: Exception | None = None
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            client = _get_client()
            response = await client.get(url, params=params)
            if response.status_code in _RETRYABLE_STATUSES:
                wait = min(
                    _RETRY_BASE_DELAY * (2 ** (attempt - 1)) + random.uniform(0.0, 0.5),
                    _RETRY_MAX_DELAY,
                )
                logger.warning(
                    "%s retryable HTTP %s (attempt %d/%d), retrying in %.2fs",
                    label, response.status_code, attempt, _MAX_RETRIES, wait,
                )
                await asyncio.sleep(wait)
                continue
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(
                "%s HTTP error (attempt %d/%d): %s",
                label, attempt, _MAX_RETRIES, e.response.status_code,
            )
            last_exc = e
            break  # non-retryable 4xx
        except httpx.RequestError as e:
            last_exc = e
            wait = min(
                _RETRY_BASE_DELAY * (2 ** (attempt - 1)) + random.uniform(0.0, 0.5),
                _RETRY_MAX_DELAY,
            )
            logger.warning(
                "%s connection error (attempt %d/%d): %s — retrying in %.2fs",
                label, attempt, _MAX_RETRIES, str(e), wait,
            )
            if attempt < _MAX_RETRIES:
                await asyncio.sleep(wait)

    from api_layer.exceptions import ExternalAPIException
    if isinstance(last_exc, httpx.HTTPStatusError):
        raise ExternalAPIException(
            detail=f"{label}: HTTP {last_exc.response.status_code}",
            error_code=error_code,
        )
    raise ExternalAPIException(
        detail=f"{label}: connection failed after {_MAX_RETRIES} attempts",
        error_code=error_code,
    )


class OpenMeteoWeatherClient:
    """Client for interacting with the Open-Meteo Weather API."""

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
        """

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
        return await _get_with_retry(
            url, params,
            error_code="OPEN_METEO_API_ERROR",
            label="Open-Meteo Weather API",
        )

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
            if isinstance(data, list):
                return data
            else:
                return [data]
        except Exception as e:
            logger.error("Open-Meteo batch API error: %s", str(e))
            raise

    async def fetch_hourly_weather(
        self,
        latitude: float,
        longitude: float,
        forecast_days: int = 1,
    ) -> dict:
        """Fetch hourly weather forecast for a given location."""

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
        return await _get_with_retry(
            url, params,
            error_code="OPEN_METEO_API_ERROR",
            label="Open-Meteo Hourly Weather API",
        )
