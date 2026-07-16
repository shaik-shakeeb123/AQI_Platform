from __future__ import annotations

import asyncio
from typing import Any, Optional
import httpx

from api_layer.config import get_settings
from api_layer.exceptions import ExternalAPIException
from api_layer.logging import get_logger

logger = get_logger(__name__)

_client: httpx.AsyncClient | None = None

def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(timeout=30.0)
    return _client


class OpenAQClient:
    """Client for interacting with the OpenAQ v3 API."""

    def __init__(self) -> None:
        settings = get_settings()
        self.base_url: str = settings.OPENAQ_BASE_URL
        self.headers: dict[str, str] = {"X-API-Key": settings.OPENAQ_API_KEY}

    async def _make_request(
        self,
        endpoint: str,
        params: dict[str, int | str] | None = None,
    ) -> dict:
        """Make an authenticated GET request to the OpenAQ API, retrying on rate limits."""
        url = f"{self.base_url}{endpoint}"
        retries = 3
        backoff = 2.0
        client = _get_client()
        
        for attempt in range(retries + 1):
            try:
                response = await client.get(
                    url, headers=self.headers, params=params
                )
                
                if response.status_code == 429:
                    if attempt >= retries:
                        break
                    reset_header = response.headers.get("X-Ratelimit-Reset")
                    try:
                        sleep_time = int(reset_header) if reset_header else int(backoff ** attempt)
                    except ValueError:
                        sleep_time = int(backoff ** attempt)
                    
                    sleep_time = min(max(sleep_time + 1, 2), 30)
                    logger.warning(
                        "OpenAQ API rate limit hit (429). Sleeping for %d seconds before retry (attempt %d/%d)...",
                        sleep_time, attempt + 1, retries
                    )
                    await asyncio.sleep(sleep_time)
                    continue
                    
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429 and attempt < retries:
                    continue
                logger.error(
                    "OpenAQ API error: %s - %s",
                    e.response.status_code,
                    e.response.text,
                )
                raise ExternalAPIException(
                    detail=f"OpenAQ API returned {e.response.status_code}",
                    error_code="OPENAQ_API_ERROR",
                )
            except httpx.RequestError as e:
                logger.error("OpenAQ API connection error: %s", str(e))
                if attempt < retries:
                    await asyncio.sleep(backoff ** attempt)
                    continue
                raise ExternalAPIException(
                    detail="Failed to connect to OpenAQ API",
                    error_code="OPENAQ_CONNECTION_ERROR",
                )
        
        raise ExternalAPIException(
            detail="OpenAQ API rate limit exceeded",
            error_code="OPENAQ_RATE_LIMIT_ERROR",
        )

    async def fetch_locations(
        self,
        countries_id: int | None = 9,
        limit: int = 100,
        page: int = 1,
        **kwargs: Any,
    ) -> dict:
        """Fetch monitoring locations from OpenAQ."""
        params: dict[str, Any] = {
            "limit": limit,
            "page": page,
        }
        if countries_id is not None:
            params["countries_id"] = countries_id
        params.update(kwargs)
        return await self._make_request("/locations", params=params)

    async def fetch_sensors(self, location_id: int) -> dict:
        """Fetch sensors for a specific location."""
        return await self._make_request(
            f"/locations/{location_id}/sensors"
        )

    async def fetch_latest_measurements(self, location_id: int) -> dict:
        """Fetch the most recent measurements for a location."""
        return await self._make_request(
            f"/locations/{location_id}/latest"
        )

    async def fetch_sensor_measurements(
        self,
        sensor_id: int,
        limit: int = 100,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> dict:
        """Fetch historical measurement data for a specific sensor."""
        params: dict[str, int | str] = {"limit": limit}
        if date_from:
            params["date_from"] = date_from
        if date_to:
            params["date_to"] = date_to
        return await self._make_request(
            f"/sensors/{sensor_id}/measurements", params=params
        )
