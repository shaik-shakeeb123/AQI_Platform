from __future__ import annotations

import asyncio
from collections import OrderedDict
from dataclasses import dataclass
from typing import Optional
import httpx

from api_layer.logging import get_logger

logger = get_logger(__name__)

_client: httpx.AsyncClient | None = None

# Global forward geocoding cache: normalized_city -> (lat, lon, country, country_code)
# Bounded to _GEOCODING_CACHE_MAX_SIZE entries; oldest entry is evicted when full.
_GEOCODING_CACHE_MAX_SIZE = 1000
_forward_geocoding_cache: OrderedDict[str, tuple[float, float, Optional[str], Optional[str]]] = OrderedDict()


def _cache_set(key: str, value: tuple[float, float, Optional[str], Optional[str]]) -> None:
    """Insert *key* into the forward geocoding LRU cache, evicting the LRU entry if full."""
    if key in _forward_geocoding_cache:
        _forward_geocoding_cache.move_to_end(key)  # promote to MRU
    _forward_geocoding_cache[key] = value
    if len(_forward_geocoding_cache) > _GEOCODING_CACHE_MAX_SIZE:
        _forward_geocoding_cache.popitem(last=False)  # evict LRU (oldest)

# City Normalization Map
CITY_NORMALIZE_MAP = {
    "bombay": "Mumbai",
    "mumbai": "Mumbai",
    "bangalore": "Bengaluru",
    "bengaluru": "Bengaluru",
    "banglore": "Bengaluru",
    "new delhi": "Delhi",
    "delhi": "Delhi",
    "secunderabad": "Hyderabad",
    "hyderabad": "Hyderabad",
    "vizag": "Visakhapatnam",
    "visakhapatnam": "Visakhapatnam",
    "madnapalle": "Madanapalle",
    "madanapalle": "Madanapalle",
    "chitoor": "Chittoor",
    "chittoor": "Chittoor",
    "anantpur": "Anantapur",
    "anantapur": "Anantapur",
    "pune": "Pune",
    "chennai": "Chennai",
    "kolkata": "Kolkata",
    "hadapsar": "Pune",  # context mapping
}

# Pre-defined canonical coordinates for immediate 0ms resolution of key cities
CANONICAL_COORDINATES = {
    "Delhi": (28.6139, 77.2090),
    "Mumbai": (19.0760, 72.8777),
    "Hyderabad": (17.3850, 78.4867),
    "Bengaluru": (12.9716, 77.5946),
    "Pune": (18.5204, 73.8567),
    "Chennai": (13.0827, 80.2707),
    "Kolkata": (22.5726, 88.3639),
    "Madanapalle": (13.6268, 78.5040),
    "Chittoor": (13.2161, 79.1003),
    "Anantapur": (14.6819, 77.6006),
    "Visakhapatnam": (17.6868, 83.2185)
}

def normalize_city_name(city: str) -> str:
    """Normalize city name to clean, trimmed, canonical spelling and casing."""
    if not city:
        return ""
    cleaned = city.strip().lower()
    return CITY_NORMALIZE_MAP.get(cleaned, city.strip().title())

def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(timeout=30.0)
    return _client

def get_coordinates_from_db(city_name: str) -> Optional[tuple[float, float]]:
    """Fetch coordinates for a city from the database cache layer."""
    try:
        from database.connection import SessionLocal
        from database.models.aqi_data import AQIData
        from sqlalchemy import func
        
        with SessionLocal() as db:
            record = (
                db.query(AQIData)
                .filter(func.lower(AQIData.city) == city_name.lower())
                .filter(AQIData.latitude.isnot(None))
                .filter(AQIData.longitude.isnot(None))
                .order_by(AQIData.recorded_at.desc())
                .first()
            )
            if record:
                return record.latitude, record.longitude
    except Exception as e:
        logger.warning(f"Failed to query coordinates from DB for '{city_name}': {e}")
    return None

async def call_nominatim_with_retry(url: str, params: dict, headers: dict, retries: int = 2) -> Optional[httpx.Response]:
    """Execute Nominatim HTTP requests with retry mechanism and rate-limiting handles."""
    client = _get_client()
    for attempt in range(retries + 1):
        try:
            # Add backoff delay to respect Nominatim usage rules
            await asyncio.sleep(1.0 + attempt * 0.5)
            response = await client.get(url, params=params, headers=headers, timeout=5.0)
            if response.status_code == 200:
                return response
            elif response.status_code == 429:
                logger.warning(f"Nominatim rate limit hit (429). Attempt {attempt + 1} of {retries + 1}")
            else:
                logger.warning(f"Nominatim returned status {response.status_code}. Attempt {attempt + 1}")
        except Exception as e:
            logger.warning(f"Nominatim query failed: {e}. Attempt {attempt + 1} of {retries + 1}")
    return None


@dataclass(frozen=True)
class GeocodingResult:
    """Rich geocoding result containing coordinates and location metadata."""
    latitude: float
    longitude: float
    country: Optional[str] = None
    country_code: Optional[str] = None


class NominatimGeocoderClient:
    """Production-grade geocoding client with normalization, global caching, retries, and fallbacks."""

    def __init__(self) -> None:
        self.geocoding_cache: dict[tuple[float, float], Optional[str]] = {}
        self.headers = {"User-Agent": "AQI-Platform-Student-Project/1.0"}

    async def reverse_geocode_city(self, lat: float, lon: float) -> Optional[str]:
        """Reverse geocode coordinates using OpenStreetMap Nominatim with caching."""
        cache_key = (round(lat, 3), round(lon, 3))
        if cache_key in self.geocoding_cache:
            logger.info("Geocoding cache hit for coordinates: %s", cache_key)
            return self.geocoding_cache[cache_key]

        await asyncio.sleep(1.0)
        
        url = f"https://nominatim.openstreetmap.org/reverse?lat={lat}&lon={lon}&format=json&accept-language=en"
        
        try:
            logger.info("Geocoding cache miss. Calling Nominatim for coordinates: (%s, %s)", lat, lon)
            client = _get_client()
            response = await client.get(url, headers=self.headers, timeout=5.0)
            if response.status_code == 200:
                address = response.json().get("address", {})
                for key in ["city", "town", "village", "municipality", "suburb", "county"]:
                    city_name = address.get(key)
                    if city_name:
                        normalized = normalize_city_name(city_name)
                        self.geocoding_cache[cache_key] = normalized
                        logger.info("Successfully resolved city: %s (normalized: %s)", city_name, normalized)
                        return normalized
        except Exception as e:
            logger.warning("Reverse geocoding failed for coordinates (%s, %s): %s", lat, lon, str(e))
            
        self.geocoding_cache[cache_key] = None
        return None

    @staticmethod
    async def geocode_address(query: str, city_context: str) -> Optional[tuple[float, float]]:
        """Geocode an address string using Nominatim, coordinate cache, database lookup, and normalization."""
        try:
            parts = query.split(",")
            if len(parts) == 2:
                return float(parts[0].strip()), float(parts[1].strip())
        except Exception:
            pass

        normalized = normalize_city_name(query)
        
        # 1. Canonical lookup
        if normalized in CANONICAL_COORDINATES:
            lat, lon = CANONICAL_COORDINATES[normalized]
            logger.info("Resolved city '%s' (normalized: '%s') from canonical map to (%s, %s)", query, normalized, lat, lon)
            return lat, lon

        # 2. Global LRU cache lookup
        if normalized in _forward_geocoding_cache:
            lat, lon, _, _ = _forward_geocoding_cache[normalized]
            _forward_geocoding_cache.move_to_end(normalized)  # promote to MRU
            logger.info("Resolved city '%s' (normalized: '%s') from cache to (%s, %s)", query, normalized, lat, lon)
            return lat, lon

        # 3. Database lookup
        db_coords = get_coordinates_from_db(normalized)
        if db_coords:
            lat, lon = db_coords
            _cache_set(normalized, (lat, lon, "India", "IN"))
            logger.info("Resolved city '%s' (normalized: '%s') from database to (%s, %s)", query, normalized, lat, lon)
            return lat, lon

        # 4. External API call with retry
        url = "https://nominatim.openstreetmap.org/search"
        headers = {"User-Agent": "AQI-Platform-Student-Project/1.0"}
        
        queries_to_try = []
        if city_context:
            queries_to_try.append(f"{normalized}, {normalize_city_name(city_context)}")
        queries_to_try.append(normalized)

        for q in queries_to_try:
            params = {"q": q, "format": "json", "limit": 1}
            logger.info("Geocoding query '%s' via Nominatim API", q)
            response = await call_nominatim_with_retry(url, params, headers)
            if response:
                try:
                    results = response.json()
                    if results:
                        lat = float(results[0]["lat"])
                        lon = float(results[0]["lon"])
                        _cache_set(normalized, (lat, lon, "India", "IN"))
                        logger.info("Successfully geocoded '%s' to (%s, %s) via Nominatim", normalized, lat, lon)
                        return lat, lon
                except Exception as e:
                    logger.error("Failed to parse Nominatim response: %s", e)

        # 5. Final fallback coordinate (only if it is a canonical city)
        if normalized in CANONICAL_COORDINATES:
            default_lat, default_lon = CANONICAL_COORDINATES[normalized]
            logger.warning("Geocoding failed for canonical city '%s'. Falling back to default coordinates (%s, %s)", query, default_lat, default_lon)
            return default_lat, default_lon

        logger.warning("Geocoding failed for unknown city '%s'. Returning None.", query)
        return None

    @staticmethod
    async def geocode_address_with_details(query: str, city_context: str) -> Optional[GeocodingResult]:
        """Geocode an address string and return full location metadata with caching and fallbacks."""
        try:
            parts = query.split(",")
            if len(parts) == 2:
                lat, lon = float(parts[0].strip()), float(parts[1].strip())
                return GeocodingResult(latitude=lat, longitude=lon)
        except Exception:
            pass

        normalized = normalize_city_name(query)
        
        # 1. Canonical lookup
        if normalized in CANONICAL_COORDINATES:
            lat, lon = CANONICAL_COORDINATES[normalized]
            logger.info("Resolved details for '%s' (normalized: '%s') from canonical map to (%s, %s)", query, normalized, lat, lon)
            return GeocodingResult(latitude=lat, longitude=lon, country="India", country_code="IN")

        # 2. Global LRU cache lookup
        if normalized in _forward_geocoding_cache:
            lat, lon, country, country_code = _forward_geocoding_cache[normalized]
            _forward_geocoding_cache.move_to_end(normalized)  # promote to MRU
            logger.info("Resolved details for '%s' (normalized: '%s') from cache to (%s, %s)", query, normalized, lat, lon)
            return GeocodingResult(latitude=lat, longitude=lon, country=country, country_code=country_code)

        # 3. Database lookup
        db_coords = get_coordinates_from_db(normalized)
        if db_coords:
            lat, lon = db_coords
            _cache_set(normalized, (lat, lon, "India", "IN"))
            logger.info("Resolved details for '%s' (normalized: '%s') from database to (%s, %s)", query, normalized, lat, lon)
            return GeocodingResult(latitude=lat, longitude=lon, country="India", country_code="IN")

        # 4. External API call with retry
        url = "https://nominatim.openstreetmap.org/search"
        headers = {"User-Agent": "AQI-Platform-Student-Project/1.0"}
        
        queries_to_try = []
        if city_context:
            queries_to_try.append(f"{normalized}, {normalize_city_name(city_context)}")
        queries_to_try.append(normalized)

        for q in queries_to_try:
            params = {"q": q, "format": "json", "limit": 1, "accept-language": "en", "addressdetails": 1}
            logger.info("Geocoding query with details '%s' via Nominatim API", q)
            response = await call_nominatim_with_retry(url, params, headers)
            if response:
                try:
                    results = response.json()
                    if results:
                        r = results[0]
                        address = r.get("address", {})
                        lat = float(r["lat"])
                        lon = float(r["lon"])
                        country = address.get("country", "India")
                        country_code = address.get("country_code", "IN").upper()
                        _cache_set(normalized, (lat, lon, country, country_code))
                        logger.info("Successfully geocoded with details '%s' to (%s, %s) via Nominatim", normalized, lat, lon)
                        return GeocodingResult(latitude=lat, longitude=lon, country=country, country_code=country_code)
                except Exception as e:
                    logger.error("Failed to parse Nominatim detailed response: %s", e)

        # 5. Final fallback GeocodingResult (only if it is a canonical city)
        if normalized in CANONICAL_COORDINATES:
            default_lat, default_lon = CANONICAL_COORDINATES[normalized]
            logger.warning("Geocoding detailed failed for '%s'. Falling back to default GeocodingResult", query)
            return GeocodingResult(latitude=default_lat, longitude=default_lon, country="India", country_code="IN")

        logger.warning("Geocoding detailed failed for unknown city '%s'. Returning None.", query)
        return None
