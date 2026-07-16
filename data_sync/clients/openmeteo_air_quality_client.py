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

# Retry configuration for transient errors (network blips, 5xx, 429).
_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 1.0   # seconds before first retry
_RETRY_MAX_DELAY = 16.0   # cap on any single sleep
_RETRYABLE_STATUSES = {429, 500, 502, 503, 504}


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(timeout=30.0)
    return _client


async def _get_with_retry(url: str, params: dict, *, error_code: str, label: str) -> dict:
    """GET *url* with exponential back-off + jitter on transient failures.

    Retries on network errors and HTTP status codes in ``_RETRYABLE_STATUSES``.
    Non-retryable 4xx errors are raised immediately.
    """
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
                "%s HTTP error (attempt %d/%d): %s — %s",
                label, attempt, _MAX_RETRIES, e.response.status_code, e.response.text[:200],
            )
            last_exc = e
            break  # non-retryable 4xx — do not retry
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

    if isinstance(last_exc, httpx.HTTPStatusError):
        raise ExternalAPIException(
            detail=f"{label}: HTTP {last_exc.response.status_code}",
            error_code=error_code,
        )
    raise ExternalAPIException(
        detail=f"{label}: connection failed after {_MAX_RETRIES} attempts",
        error_code=error_code,
    )


class OpenMeteoAirQualityClient:
    """Client for interacting with the Open-Meteo Air Quality API for AQI fallbacks."""

    def __init__(self) -> None:
        settings = get_settings()
        self.base_url: str = settings.OPEN_METEO_BASE_URL

    async def fetch_air_quality(
        self,
        latitude: float,
        longitude: float,
    ) -> dict:
        """Fetch current air quality data for a given location from Open-Meteo Air Quality API."""

        url = "https://air-quality-api.open-meteo.com/v1/air-quality"
        params: dict[str, str | float] = {
            "latitude": latitude,
            "longitude": longitude,
            "current": "pm10,pm2_5,carbon_monoxide,nitrogen_dioxide,sulphur_dioxide,ozone",
            "timezone": "auto",
        }
        return await _get_with_retry(
            url, params,
            error_code="OPEN_METEO_AIR_QUALITY_API_ERROR",
            label="Open-Meteo Air Quality API",
        )

    async def fetch_air_quality_multi(
        self,
        latitudes: list[float],
        longitudes: list[float],
    ) -> list[dict]:
        """Fetch current air quality data for multiple locations in batch."""
        if not latitudes or not longitudes or len(latitudes) != len(longitudes):
            return []

        url = "https://air-quality-api.open-meteo.com/v1/air-quality"
        results = []

        # Batch coordinates in chunks of 25 to avoid HTTP 414 (URI Too Large).
        # With 500 coords the URL exceeds ~10,000 chars; 25 keeps it under 2,000.
        batch_size = 25
        for i in range(0, len(latitudes), batch_size):
            lat_batch = latitudes[i:i+batch_size]
            lon_batch = longitudes[i:i+batch_size]

            params: dict[str, str] = {
                "latitude": ",".join(map(str, lat_batch)),
                "longitude": ",".join(map(str, lon_batch)),
                "current": "pm10,pm2_5,carbon_monoxide,nitrogen_dioxide,sulphur_dioxide,ozone",
                "timezone": "auto",
            }
            data = await _get_with_retry(
                url, params,
                error_code="OPEN_METEO_AIR_QUALITY_API_ERROR",
                label="Open-Meteo Air Quality API (multi)",
            )
            if isinstance(data, list):
                results.extend(data)
            else:
                results.append(data)

        return results
