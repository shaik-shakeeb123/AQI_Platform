"""Provider abstraction and OpenAQ implementation."""

from __future__ import annotations

import asyncio
from typing import Any
import httpx

from api_layer.config import get_settings
from data_sync.ingestion.governor import RequestGovernor
from data_sync.ingestion.metrics import IngestionMetrics

class OpenAQAdapter:
    """Adapter for OpenAQ v3 API, governed by RequestGovernor."""
    
    def __init__(self, metrics: IngestionMetrics | None = None) -> None:
        settings = get_settings()
        self.base_url = settings.OPENAQ_BASE_URL
        self.headers = {
            "X-API-Key": settings.OPENAQ_API_KEY,
            "User-Agent": getattr(settings, "OPENAQ_USER_AGENT", "AQIPlatform/1.0 (responsible-use)"),
        }
        self.metrics = metrics or IngestionMetrics()
        
        self.governor = RequestGovernor(
            provider_name="OpenAQ",
            max_concurrency=getattr(settings, "MAX_PROVIDER_CONCURRENCY", 10),
            requests_per_minute=getattr(settings, "OPENAQ_REQUESTS_PER_MINUTE", 45),
            hourly_budget=getattr(settings, "OPENAQ_HOURLY_REQUEST_BUDGET", 1800),
            max_retries=3,
            base_backoff=2.0,
            metrics=self.metrics
        )
        self._client = httpx.AsyncClient(timeout=30.0)

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

    async def _make_governed_request(self, endpoint: str, params: dict[str, Any] | None = None) -> dict:
        """Make an API request through the governor."""
        url = f"{self.base_url}{endpoint}"
        
        async def _req() -> dict:
            response = await self._client.get(url, headers=self.headers, params=params)
            response.raise_for_status()
            return response.json()
            
        return await self.governor.execute(
            operation=_req,
            on_retry=lambda: setattr(self.metrics, "openaq_retries", self.metrics.openaq_retries + 1),
            on_error=lambda: setattr(self.metrics, "openaq_errors", self.metrics.openaq_errors + 1),
        )

    async def get_locations(
        self, 
        countries_id: int = 9, 
        page: int = 1, 
        limit: int = 100, 
        order_by: str = "id", 
        sort_order: str = "asc"
    ) -> dict:
        """Fetch a page of locations."""
        params = {
            "countries_id": countries_id,
            "page": page,
            "limit": limit,
            "order_by": order_by,
            "sort_order": sort_order
        }
        return await self._make_governed_request("/locations", params)

    async def get_latest_measurements(self, location_id: int) -> dict:
        """Fetch latest measurements for a location."""
        return await self._make_governed_request(f"/locations/{location_id}/latest")

