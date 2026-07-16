from __future__ import annotations

from typing import Any, Optional, List, Dict
import asyncio
import random
import httpx

from api_layer.config import get_settings
from api_layer.logging import get_logger

logger = get_logger(__name__)

_client: httpx.AsyncClient | None = None

# Retry configuration for transient OSRM errors.
_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 0.5
_RETRY_MAX_DELAY = 8.0
_RETRYABLE_STATUSES = {429, 500, 502, 503, 504}


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(timeout=30.0)
    return _client


def _format_osrm_route(route: dict, index: int) -> dict[str, Any]:
    """Format a single OSRM route into the standard internal format."""
    distance_meters = route.get("distance", 0.0)
    duration_seconds = route.get("duration", 0.0)
    geometry_geojson = route.get("geometry", {})
    raw_coords = geometry_geojson.get("coordinates", [])
    formatted_coords = [[coord[1], coord[0]] for coord in raw_coords]

    route_names = ["Primary Route", "Alternative Route B", "Alternative Route C",
                   "Alternative Route D", "Alternative Route E"]

    return {
        "route_id": f"route_{chr(65 + index)}",  # route_A, route_B, route_C
        "route_name": route_names[index] if index < len(route_names) else f"Alternative Route {chr(65 + index)}",
        "distance_km": round(distance_meters / 1000.0, 2),
        "estimated_time_mins": round(duration_seconds / 60.0, 2),
        "geometry": formatted_coords,
        "raw_route_data": route,
    }


class OSRMClient:
    """Client for driving route calculations via OSRM."""

    @staticmethod
    async def geocode_address(query: str, city_context: str) -> Optional[tuple[float, float]]:
        """Delegates geocoding operation to NominatimGeocoderClient."""
        from data_sync.clients.nominatim_client import NominatimGeocoderClient
        return await NominatimGeocoderClient.geocode_address(query, city_context)

    @staticmethod
    async def get_optimized_route(
        start_lat: float,
        start_lon: float,
        dest_lat: float,
        dest_lon: float
    ) -> Optional[dict[str, Any]]:
        """Get a single optimal route from OSRM. Backward-compatible with existing callers."""

        settings = get_settings()
        url = (
            f"{settings.OSRM_BASE_URL.rstrip('/')}/route/v1/driving/"
            f"{start_lon},{start_lat};{dest_lon},{dest_lat}"
        )
        params = {
            "overview": "full",
            "geometries": "geojson",
            "alternatives": "false"
        }
        logger.info("Querying OSRM: %s with params %s", url, params)
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                client = _get_client()
                response = await client.get(url, params=params, timeout=5.0)
                if response.status_code in _RETRYABLE_STATUSES:
                    wait = min(_RETRY_BASE_DELAY * (2 ** (attempt - 1)) + random.uniform(0.0, 0.3), _RETRY_MAX_DELAY)
                    logger.warning("OSRM retryable HTTP %s (attempt %d/%d), retrying in %.2fs", response.status_code, attempt, _MAX_RETRIES, wait)
                    await asyncio.sleep(wait)
                    continue
                if response.status_code == 200:
                    data = response.json()
                    routes = data.get("routes", [])
                    if routes:
                        return _format_osrm_route(routes[0], 0)
                return None
            except httpx.TimeoutException:
                logger.warning("OSRM request timed out (attempt %d/%d)", attempt, _MAX_RETRIES)
                if attempt < _MAX_RETRIES:
                    await asyncio.sleep(_RETRY_BASE_DELAY * attempt)
            except Exception as e:
                logger.error("OSRM route query failed (attempt %d/%d): %s", attempt, _MAX_RETRIES, str(e))
                if attempt < _MAX_RETRIES:
                    await asyncio.sleep(_RETRY_BASE_DELAY * attempt)
        return None

    @staticmethod
    async def get_routes_with_alternatives(
        start_lat: float,
        start_lon: float,
        dest_lat: float,
        dest_lon: float,
        alternatives: bool = True,
        max_alternatives: int = 3,
        timeout: float = 10.0,
    ) -> List[dict[str, Any]]:
        """Get primary route plus alternative routes from OSRM.

        Args:
            start_lat: Start latitude.
            start_lon: Start longitude.
            dest_lat: Destination latitude.
            dest_lon: Destination longitude.
            alternatives: Whether to request alternative routes.
            max_alternatives: Maximum number of alternatives to request.
            timeout: Request timeout in seconds.

        Returns:
            List of formatted route dicts. Always returns at least one route if OSRM succeeds.
            Each route has: route_id, route_name, distance_km, estimated_time_mins, geometry, raw_route_data.
        """
        settings = get_settings()
        url = (
            f"{settings.OSRM_BASE_URL.rstrip('/')}/route/v1/driving/"
            f"{start_lon},{start_lat};{dest_lon},{dest_lat}"
        )
        params = {
            "overview": "full",
            "geometries": "geojson",
            "alternatives": "true" if alternatives else "false",
        }
        if alternatives:
            params["alternatives"] = str(min(max_alternatives, 3))  # OSRM max is 3

        logger.info("Querying OSRM with alternatives: %s params=%s", url, params)

        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                client = _get_client()
                response = await client.get(url, params=params, timeout=timeout)
                if response.status_code in _RETRYABLE_STATUSES:
                    wait = min(_RETRY_BASE_DELAY * (2 ** (attempt - 1)) + random.uniform(0.0, 0.3), _RETRY_MAX_DELAY)
                    logger.warning("OSRM retryable HTTP %s (attempt %d/%d), retrying in %.2fs", response.status_code, attempt, _MAX_RETRIES, wait)
                    await asyncio.sleep(wait)
                    continue
                if response.status_code == 200:
                    data = response.json()
                    osrm_routes = data.get("routes", [])
                    if osrm_routes:
                        formatted = [_format_osrm_route(r, i) for i, r in enumerate(osrm_routes)]
                        logger.info("OSRM returned %d route(s)", len(formatted))
                        return formatted
                else:
                    logger.warning("OSRM returned status %d: %s", response.status_code, response.text[:200])
                    return []
            except httpx.TimeoutException:
                logger.error("OSRM request timed out after %.1fs (attempt %d/%d)", timeout, attempt, _MAX_RETRIES)
                if attempt < _MAX_RETRIES:
                    await asyncio.sleep(_RETRY_BASE_DELAY * attempt)
            except Exception as e:
                logger.error("OSRM route query failed (attempt %d/%d): %s", attempt, _MAX_RETRIES, str(e))
                if attempt < _MAX_RETRIES:
                    await asyncio.sleep(_RETRY_BASE_DELAY * attempt)

        return []
