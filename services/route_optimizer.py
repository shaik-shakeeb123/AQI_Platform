import logging
import math
import asyncio
import time
from datetime import datetime
from functools import cmp_to_key
from collections import OrderedDict
from typing import List, Dict, Any, Optional, Tuple
from sqlalchemy.orm import Session
from api_layer.logging import get_logger
import httpx

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Module-level geocoding cache (shared across requests within the process)
# Key: normalized query string -> (lat, lon) or None
# ---------------------------------------------------------------------------
_GEOCODE_CACHE_MAX = 256
_geocode_cache: OrderedDict[str, Optional[Tuple[float, float]]] = OrderedDict()

# ---------------------------------------------------------------------------
# Shared HTTP client for cross-request connection pooling
# ---------------------------------------------------------------------------
_http_client: Optional[httpx.AsyncClient] = None

def _get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(timeout=15.0)
    return _http_client

NOMINATIM_BASE = "https://nominatim.openstreetmap.org"
NOMINATIM_HEADERS = {"User-Agent": "AQI-Platform-Student-Project/1.0 (admin@aqiplatform.com)"}
NOMINATIM_SLEEP_SECS = 0.5  # Nominatim allows 1 req/s; 0.5s is safe with retries
OSRM_BASE = "https://router.project-osrm.org"
OPEN_METEO_AQ_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
OPEN_METEO_AQ_FIELDS = "pm10,pm2_5,carbon_monoxide,nitrogen_dioxide,sulphur_dioxide,ozone"
STATION_RADIUS_LIMIT_KM = 3.0
SAMPLE_TARGET_LONG = 150   # For routes > 150 km
SAMPLE_TARGET_SHORT = 100  # For shorter routes


def _geocode_cache_key(query: str, city_context: str) -> str:
    """Build a stable cache key for geocoding lookups."""
    return f"{query.strip().lower()}|{city_context.strip().lower()}"


def _haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate the great circle distance between two points in kilometers."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def _sample_route_coords(coords: List[List[float]], distance_km: float) -> List[List[float]]:
    """Sample route coordinates adaptively based on route length."""
    target = SAMPLE_TARGET_LONG if distance_km > 150 else SAMPLE_TARGET_SHORT
    if len(coords) <= target:
        return coords
    step = (len(coords) - 1) / (target - 1)
    return [coords[int(round(i * step))] for i in range(target)]


def _parse_meteo_aqi(resp: dict) -> Tuple[Optional[float], Optional[str]]:
    """Extract AQI and dominant pollutant from a single Open-Meteo response."""
    from services.dominant_pollutant import calculate_overall_aqi
    current = resp.get("current", {})
    pm25 = current.get("pm2_5")
    pm10 = current.get("pm10")
    no2 = current.get("nitrogen_dioxide")
    so2 = current.get("sulphur_dioxide")
    o3 = current.get("ozone")
    raw_co = current.get("carbon_monoxide")
    co = raw_co / 1000.0 if raw_co is not None else None
    aqi_val, _category, dom_poll = calculate_overall_aqi(
        pm25=pm25, pm10=pm10, no2=no2, so2=so2, co=co, o3=o3
    )
    return aqi_val, dom_poll


def _get_age_hours(recorded_at: Optional[datetime], ref_time: datetime) -> float:
    """Safely calculate age of a record in hours, defaulting to 0.0 if missing (backward-compatible / mocks)."""
    if not recorded_at:
        return 0.0
    rec = recorded_at.replace(tzinfo=None)
    ref = ref_time.replace(tzinfo=None)
    return (ref - rec).total_seconds() / 3600.0


def _compare_stations(c1: Tuple[Any, float, float, int], c2: Tuple[Any, float, float, int]) -> int:
    """Comparator for sorting candidate stations.
    
    Candidates are structured as: (station, distance_km, age_hours, quality_score)
    Sorting principles:
    1. Distance: if within 100m (0.1 km), they are considered "nearly identical".
    2. Freshness: if distances are nearly identical, the fresher station (lower age) wins.
    3. Data Quality: if age is close (within 1 hour), the one with higher quality (more pollutants) wins.
    4. Exact Distance: absolute tie-breaker.
    """
    st1, dist1, age1, qual1 = c1
    st2, dist2, age2, qual2 = c2
    
    dist_diff = dist1 - dist2
    if abs(dist_diff) <= 0.1:  # within 100 meters
        age_diff = age1 - age2
        if abs(age_diff) > 1.0:  # more than 1 hour age difference
            return -1 if age_diff < 0 else 1
        
        # Higher quality (more pollutants) is better
        if qual1 != qual2:
            return -1 if qual1 > qual2 else 1
            
        # Tie break on absolute distance
        return -1 if dist_diff < 0 else 1
    else:
        # Distance difference is significant, closer wins
        return -1 if dist_diff < 0 else 1


class RouteOptimizerService:
    """Service to compute healthy routing options using OSRM, geocoding, and DB telemetry."""

    # ------------------------------------------------------------------
    # Backward-compatible static methods (used by safe_window endpoint)
    # ------------------------------------------------------------------

    @staticmethod
    async def geocode_address(query: str, city_context: str) -> Optional[Tuple[float, float]]:
        """Geocode an address using the shared client."""
        client = _get_http_client()
        return await RouteOptimizerService._geocode_with_client(client, query, city_context)

    @staticmethod
    async def get_optimized_route(
        start_lat: float, start_lon: float,
        dest_lat: float, dest_lon: float,
    ) -> Optional[Dict[str, Any]]:
        """Fetch driving route using the shared client."""
        client = _get_http_client()
        return await RouteOptimizerService._osrm_route_with_client(
            client, start_lat, start_lon, dest_lat, dest_lon
        )

    # ------------------------------------------------------------------
    # Internal helpers (use shared client)
    # ------------------------------------------------------------------

    @staticmethod
    async def _geocode_with_client(
        client: httpx.AsyncClient, query: str, city_context: str
    ) -> Optional[Tuple[float, float]]:
        """Geocode a single address string via Nominatim with caching."""
        # 0. Check if query is already coordinates to avoid Nominatim geocoding overhead
        try:
            parts = query.split(",")
            if len(parts) == 2:
                return float(parts[0].strip()), float(parts[1].strip())
        except Exception:
            pass

        key = _geocode_cache_key(query, city_context)
        if key in _geocode_cache:
            cached = _geocode_cache[key]
            if cached is not None:
                logger.debug("Geocode cache hit: %s -> %s", query, cached)
            return cached

        await asyncio.sleep(NOMINATIM_SLEEP_SECS)

        # Try with city context first (for ambiguous localities)
        queries_to_try = []
        if city_context:
            queries_to_try.append(f"{query}, {city_context}")
        queries_to_try.append(query)

        last_exception = None
        for q in queries_to_try:
            url = f"{NOMINATIM_BASE}/search"
            params = {"q": q, "format": "json", "limit": 1}
            logger.info(f"Nominatim Request URL: {url} | Params: {params} | Headers: {NOMINATIM_HEADERS}")
            start_t = time.time()
            try:
                resp = await client.get(
                    url,
                    params=params,
                    headers=NOMINATIM_HEADERS,
                    timeout=5.0,
                )
                duration = round((time.time() - start_t) * 1000, 2)
                logger.info(f"Nominatim Response Status: {resp.status_code} | Duration: {duration}ms | Body: {resp.text}")
                
                if resp.status_code == 200:
                    results = resp.json()
                    if results:
                        lat = float(results[0]["lat"])
                        lon = float(results[0]["lon"])
                        _geocode_cache[key] = (lat, lon)
                        if len(_geocode_cache) > _GEOCODE_CACHE_MAX:
                            _geocode_cache.popitem(last=False)
                        return lat, lon
                    else:
                        last_exception = Exception(f"Nominatim returned an empty result for '{q}'")
                else:
                    raise Exception(f"Nominatim returned HTTP {resp.status_code}: {resp.text}")
                    
            except httpx.TimeoutException:
                duration = round((time.time() - start_t) * 1000, 2)
                logger.error(f"Nominatim Request timed out after {duration}ms")
                raise Exception("Nominatim request timed out")
            except Exception as e:
                logger.error(f"Nominatim Request Failed: {str(e)}")
                raise e
        
        # If we exhausted queries and only had empty results
        if last_exception:
            raise last_exception

        _geocode_cache[key] = None
        if len(_geocode_cache) > _GEOCODE_CACHE_MAX:
            _geocode_cache.popitem(last=False)
        return None

    @staticmethod
    async def _osrm_route_with_client(
        client: httpx.AsyncClient,
        start_lat: float, start_lon: float,
        dest_lat: float, dest_lon: float,
    ) -> Optional[Dict[str, Any]]:
        """Fetch driving route from OSRM using the shared client."""
        url = (
            f"{OSRM_BASE}/route/v1/driving/"
            f"{start_lon},{start_lat};{dest_lon},{dest_lat}"
        )
        params = {"overview": "full", "geometries": "geojson", "alternatives": "false"}
        logger.info(f"OSRM Request URL: {url} | Params: {params}")
        start_t = time.time()
        try:
            resp = await client.get(url, params=params, timeout=10.0)
            duration = round((time.time() - start_t) * 1000, 2)
            logger.info(f"OSRM Response Status: {resp.status_code} | Duration: {duration}ms | Body (truncated): {resp.text[:200]}")
            
            if resp.status_code == 200:
                try:
                    data = resp.json()
                except Exception:
                    raise Exception("OSRM returned invalid JSON")
                
                routes = data.get("routes", [])
                if routes:
                    primary = routes[0]
                    geometry = primary.get("geometry", {})
                    raw_coords = geometry.get("coordinates", [])
                    formatted = [[c[1], c[0]] for c in raw_coords]
                    return {
                        "distance_km": round(primary.get("distance", 0.0) / 1000.0, 2),
                        "estimated_time_mins": round(primary.get("duration", 0.0) / 60.0, 2),
                        "geometry": formatted,
                        "raw_route_data": primary,
                    }
                else:
                    raise Exception("OSRM returned an empty route result")
            else:
                raise Exception(f"OSRM returned HTTP {resp.status_code}: {resp.text}")
                
        except httpx.TimeoutException:
            duration = round((time.time() - start_t) * 1000, 2)
            logger.error(f"OSRM Request timed out after {duration}ms")
            raise Exception("OSRM request timed out")
        except Exception as e:
            if "OSRM returned HTTP" in str(e) or "invalid JSON" in str(e) or "empty route result" in str(e) or "timed out" in str(e):
                logger.error(f"OSRM Request Failed: {str(e)}")
                raise e
            else:
                logger.error(f"OSRM Request Failed (Connection): {str(e)}")
                raise Exception(f"OSRM connection failed: {str(e)}")

    @staticmethod
    async def _fetch_meteo_batch(
        client: httpx.AsyncClient,
        lats: List[float],
        lons: List[float],
    ) -> List[dict]:
        """Fetch Open-Meteo AQ for a batch of coordinates, chunked to avoid URI overflow."""
        if not lats or not lons or len(lats) != len(lons):
            return []
        results: List[dict] = []
        batch_size = 25
        for i in range(0, len(lats), batch_size):
            lat_batch = lats[i : i + batch_size]
            lon_batch = lons[i : i + batch_size]
            params = {
                "latitude": ",".join(map(str, lat_batch)),
                "longitude": ",".join(map(str, lon_batch)),
                "current": OPEN_METEO_AQ_FIELDS,
                "timezone": "auto",
            }
            try:
                resp = await client.get(OPEN_METEO_AQ_URL, params=params, timeout=15.0)
                resp.raise_for_status()
                data = resp.json()
                if isinstance(data, list):
                    results.extend(data)
                else:
                    results.append(data)
            except Exception as e:
                logger.error("Open-Meteo AQ batch call failed: %s", e)
        return results

    @staticmethod
    def _find_freshness_aware_station(
        lat: float,
        lon: float,
        stations: List[Any],
        ref_time: datetime
    ) -> Tuple[Optional[Any], float, str, List[Tuple[Any, float, float, int]]]:
        """Find the best station for the given coords based on distance, freshness and tiering.
        
        Returns (selected_station, distance_km, status, level3_candidates)
        where status is 'fresh', 'stale', or 'fallback'.
        """
        candidates = []
        for st in stations:
            st_lat = getattr(st, "latitude", None)
            st_lon = getattr(st, "longitude", None)
            if st_lat is None or st_lon is None:
                continue
            dist = _haversine_distance(lat, lon, st_lat, st_lon)
            if dist <= STATION_RADIUS_LIMIT_KM:
                recorded_at = getattr(st, "recorded_at", None)
                age_hours = _get_age_hours(recorded_at, ref_time)
                # Quality score is count of non-null pollutants
                pollutants_list = [
                    getattr(st, "pm25", None), getattr(st, "pm10", None),
                    getattr(st, "no2", None), getattr(st, "so2", None),
                    getattr(st, "co", None), getattr(st, "o3", None)
                ]
                qual = sum(1 for p in pollutants_list if p is not None)
                candidates.append((st, dist, age_hours, qual))

        if not candidates:
            return None, float("inf"), "fallback", []

        # Tiers of freshness
        level1 = [c for c in candidates if c[2] <= 24.0]
        level2 = [c for c in candidates if 24.0 < c[2] <= 72.0]
        level3 = [c for c in candidates if c[2] > 72.0]

        if level1:
            best = sorted(level1, key=cmp_to_key(_compare_stations))[0]
            return best[0], best[1], "fresh", level3
        elif level2:
            best = sorted(level2, key=cmp_to_key(_compare_stations))[0]
            return best[0], best[1], "fresh", level3

        # Level 3 is stale, fallback to Open-Meteo is preferred first.
        # We return the level3 candidates so the caller can fall back to Open-Meteo,
        # but keep level3 station as last resort.
        return None, float("inf"), "fallback", level3

    @staticmethod
    def _aqi_from_station(station: Any) -> Optional[float]:
        """Extract AQI from a station ORM object, returning None if unavailable."""
        return getattr(station, "aqi", None)

    @staticmethod
    def _dominant_from_station(station: Any) -> Optional[str]:
        return getattr(station, "dominant_pollutant", None)

    # ------------------------------------------------------------------
    # Spatial station query (single DB call for entire route bbox)
    # ------------------------------------------------------------------

    @staticmethod
    def _query_stations_in_bbox(
        db: Session,
        lats: List[float],
        lons: List[float],
    ) -> List[Any]:
        """Query latest records per station within the bounding box of the route."""
        if not lats or not lons:
            return []
        from sqlalchemy import func
        from database.models.aqi_data import AQIData

        LAT_BUFFER = 0.05
        LON_BUFFER = 0.05
        min_lat = min(lats) - LAT_BUFFER
        max_lat = max(lats) + LAT_BUFFER
        min_lon = min(lons) - LON_BUFFER
        max_lon = max(lons) + LON_BUFFER

        try:
            query_base = (
                db.query(
                    AQIData.location_name,
                    func.max(AQIData.recorded_at).label("max_recorded_at"),
                )
                .filter(
                    AQIData.latitude >= min_lat,
                    AQIData.latitude <= max_lat,
                    AQIData.longitude >= min_lon,
                    AQIData.longitude <= max_lon,
                )
                .group_by(AQIData.location_name)
            )
            subq = query_base.subquery()
            return (
                db.query(AQIData)
                .join(
                    subq,
                    (AQIData.location_name == subq.c.location_name)
                    & (AQIData.recorded_at == subq.c.max_recorded_at),
                )
                .all()
            )
        except Exception as e:
            logger.error("Spatial station query failed: %s", e)
            return []

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    @staticmethod
    async def get_optimized_exposure_route(
        city: Optional[str],
        start_point: str,
        destination: str,
        db: Optional[Session] = None,
        stations: Optional[List[Any]] = None,
        departure_time: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Compute AQI-optimized route with independent source/destination AQI and freshness selection."""
        start_time = time.time()
        ref_time = datetime.utcnow()
        try:
            client = _get_http_client()
            
            # ── 1. Geocode (shared client, cached) ──────────────────
            start_coords = await RouteOptimizerService._geocode_with_client(
                client, start_point, ""
            )
            if not start_coords and city:
                start_coords = await RouteOptimizerService._geocode_with_client(
                    client, start_point, city
                )

            dest_coords = await RouteOptimizerService._geocode_with_client(
                client, destination, ""
            )

            if not start_coords or not dest_coords:
                logger.error("Could not resolve coordinates for start or destination.")
                return None

            start_lat, start_lon = start_coords
            dest_lat, dest_lon = dest_coords

            # ── 2. OSRM routing (shared client) ────────────────────
            route_info = await RouteOptimizerService._osrm_route_with_client(
                client, start_lat, start_lon, dest_lat, dest_lon
            )
            if not route_info:
                logger.error("OSRM routing failed.")
                return None

            distance_km = route_info["distance_km"]
            estimated_time_mins = route_info["estimated_time_mins"]
            formatted_coords = route_info["geometry"]
            primary_route = route_info["raw_route_data"]
            distance_meters = primary_route.get("distance", 0.0)
            duration_seconds = primary_route.get("duration", 0.0)

            # ── 3. Adaptive route sampling ─────────────────────────
            formatted_coords = _sample_route_coords(formatted_coords, distance_km)

            # ── 4. Spatial DB query in thread pool ─────────────────
            resolved_stations: List[Any] = []
            if db is not None:
                all_lats = [start_lat] + [pt[0] for pt in formatted_coords] + [dest_lat]
                all_lons = [start_lon] + [pt[1] for pt in formatted_coords] + [dest_lon]
                
                # Execute blocking DB query in background thread
                resolved_stations = await asyncio.to_thread(
                    RouteOptimizerService._query_stations_in_bbox,
                    db, all_lats, all_lons
                )
                logger.info(
                    "Spatial query found %d stations for route bbox.", len(resolved_stations)
                )
            elif stations is not None:
                resolved_stations = stations

            # ── 5. Station classification & Freshness Selection ────
            # Per-request caches for station lookup to prevent redundant calculations
            station_lookup_cache: Dict[Tuple[float, float], Tuple[Optional[Any], float, str, List[Tuple[Any, float, float, int]]]] = {}

            def get_cached_station(pt_lat: float, pt_lon: float) -> Tuple[Optional[Any], float, str, List[Tuple[Any, float, float, int]]]:
                snap_pt = (round(pt_lat, 4), round(pt_lon, 4))
                if snap_pt not in station_lookup_cache:
                    station_lookup_cache[snap_pt] = RouteOptimizerService._find_freshness_aware_station(
                        pt_lat, pt_lon, resolved_stations, ref_time
                    )
                return station_lookup_cache[snap_pt]

            # Classify source and destination
            source_station, source_dist, source_status, source_l3 = get_cached_station(start_lat, start_lon)
            dest_station, dest_dist, dest_status, dest_l3 = get_cached_station(dest_lat, dest_lon)

            # Classify route points
            route_points_needing_meteo: List[Tuple[int, float, float, List[Tuple[Any, float, float, int]]]] = []
            point_station_mappings: Dict[int, Tuple[Any, float, str]] = {}

            for idx, pt in enumerate(formatted_coords):
                st, dist, status, l3_cands = get_cached_station(pt[0], pt[1])
                if status == "fresh":
                    point_station_mappings[idx] = (st, dist, "fresh")
                else:
                    route_points_needing_meteo.append((idx, pt[0], pt[1], l3_cands))

            # Collect Open-Meteo fallback coordinates
            meteo_coords_map: Dict[Tuple[float, float], Tuple[float, float]] = {}
            if source_status == "fallback":
                key = (round(start_lat, 3), round(start_lon, 3))
                meteo_coords_map[key] = (start_lat, start_lon)
            if dest_status == "fallback":
                key = (round(dest_lat, 3), round(dest_lon, 3))
                meteo_coords_map[key] = (dest_lat, dest_lon)
            for _, lat, lon, _ in route_points_needing_meteo:
                key = (round(lat, 3), round(lon, 3))
                if key not in meteo_coords_map:
                    meteo_coords_map[key] = (lat, lon)

            # Fetch Open-Meteo batch
            meteo_aqi_values: Dict[Tuple[float, float], Tuple[Optional[float], Optional[str]]] = {}
            if meteo_coords_map:
                snap_keys = list(meteo_coords_map.keys())
                unique_lats = [v[0] for v in meteo_coords_map.values()]
                unique_lons = [v[1] for v in meteo_coords_map.values()]
                try:
                    meteo_responses = await RouteOptimizerService._fetch_meteo_batch(
                        client, unique_lats, unique_lons
                    )
                    for snap_key, resp in zip(snap_keys, meteo_responses):
                        aqi_val, dom_poll = _parse_meteo_aqi(resp)
                        if aqi_val is not None:
                            meteo_aqi_values[snap_key] = (aqi_val, dom_poll)
                except Exception as e:
                    logger.error("Open-Meteo batch AQI failed: %s", e)

            # ── 6. Map source and destination AQI ──────────────────
            source_aqi: Optional[float] = None
            source_dom_poll: Optional[str] = None
            source_fallback_time: Optional[datetime] = None
            
            if source_status == "fresh":
                source_aqi = RouteOptimizerService._aqi_from_station(source_station)
                source_dom_poll = RouteOptimizerService._dominant_from_station(source_station)
            else:
                # Try Open-Meteo
                key = (round(start_lat, 3), round(start_lon, 3))
                result = meteo_aqi_values.get(key)
                if result:
                    source_aqi, source_dom_poll = result
                    source_status = "fallback"
                    source_fallback_time = ref_time
                elif source_l3:
                    # Fallback to level3 stale station
                    best_l3 = sorted(source_l3, key=lambda c: c[2])[0]
                    source_station, source_dist = best_l3[0], best_l3[1]
                    source_aqi = RouteOptimizerService._aqi_from_station(source_station)
                    source_dom_poll = RouteOptimizerService._dominant_from_station(source_station)
                    source_status = "stale"

            destination_aqi: Optional[float] = None
            destination_dom_poll: Optional[str] = None
            dest_fallback_time: Optional[datetime] = None

            if dest_status == "fresh":
                destination_aqi = RouteOptimizerService._aqi_from_station(dest_station)
                destination_dom_poll = RouteOptimizerService._dominant_from_station(dest_station)
            else:
                # Try Open-Meteo
                key = (round(dest_lat, 3), round(dest_lon, 3))
                result = meteo_aqi_values.get(key)
                if result:
                    destination_aqi, destination_dom_poll = result
                    dest_status = "fallback"
                    dest_fallback_time = ref_time
                elif dest_l3:
                    # Fallback to level3 stale station
                    best_l3 = sorted(dest_l3, key=lambda c: c[2])[0]
                    dest_station, dest_dist = best_l3[0], best_l3[1]
                    destination_aqi = RouteOptimizerService._aqi_from_station(dest_station)
                    destination_dom_poll = RouteOptimizerService._dominant_from_station(dest_station)
                    dest_status = "stale"

            # ── 7. Map route points & segments ────────────────────
            segments: List[Dict[str, Any]] = []
            current_coords: List[List[float]] = []
            current_color: Optional[str] = None
            point_aqis: List[Optional[float]] = []
            max_aqi = 0.0
            dominant_poll: Optional[str] = None
            real_aqi_count = 0

            # For data quality metrics tracking
            unique_stations_used: Dict[str, float] = {}  # name -> age_hours
            fallback_points_count = 0

            # Map unique stations for source/dest if they used database
            if source_status in ("fresh", "stale") and source_station:
                st_name = getattr(source_station, "location_name", "Unknown Station")
                recorded_at = getattr(source_station, "recorded_at", None)
                age = _get_age_hours(recorded_at, ref_time)
                unique_stations_used[st_name] = age
            if dest_status in ("fresh", "stale") and dest_station:
                st_name = getattr(dest_station, "location_name", "Unknown Station")
                recorded_at = getattr(dest_station, "recorded_at", None)
                age = _get_age_hours(recorded_at, ref_time)
                unique_stations_used[st_name] = age

            for idx, pt in enumerate(formatted_coords):
                lat, lon = pt[0], pt[1]
                pt_status = "fallback"
                pt_st = None
                pt_dist = float("inf")

                if idx in point_station_mappings:
                    pt_st, pt_dist, pt_status = point_station_mappings[idx]
                    aqi_val = RouteOptimizerService._aqi_from_station(pt_st)
                    dom_poll = RouteOptimizerService._dominant_from_station(pt_st)
                    if pt_st:
                        st_name = getattr(pt_st, "location_name", "Unknown Station")
                        recorded_at = getattr(pt_st, "recorded_at", None)
                        age = _get_age_hours(recorded_at, ref_time)
                        unique_stations_used[st_name] = age
                else:
                    # Snapped Open-Meteo check
                    snap_key = (round(lat, 3), round(lon, 3))
                    result = meteo_aqi_values.get(snap_key)
                    if result:
                        aqi_val, dom_poll = result
                        pt_status = "fallback"
                        fallback_points_count += 1
                    else:
                        # Try level3 stale stations
                        l3_cands = next((x[3] for x in route_points_needing_meteo if x[0] == idx), [])
                        if l3_cands:
                            best_l3 = sorted(l3_cands, key=lambda c: c[2])[0]
                            pt_st, pt_dist = best_l3[0], best_l3[1]
                            aqi_val = RouteOptimizerService._aqi_from_station(pt_st)
                            dom_poll = RouteOptimizerService._dominant_from_station(pt_st)
                            pt_status = "stale"
                            if pt_st:
                                st_name = getattr(pt_st, "location_name", "Unknown Station")
                                recorded_at = getattr(pt_st, "recorded_at", None)
                                age = _get_age_hours(recorded_at, ref_time)
                                unique_stations_used[st_name] = age
                        else:
                            aqi_val, dom_poll = None, None
                            pt_status = "fallback"
                            fallback_points_count += 1

                if aqi_val is not None:
                    real_aqi_count += 1
                point_aqis.append(aqi_val)
                if aqi_val is not None and aqi_val > max_aqi:
                    max_aqi = aqi_val
                    dominant_poll = dom_poll

                color = "gray" if aqi_val is None else "green"
                if aqi_val is not None and aqi_val > 200:
                    color = "red"
                elif aqi_val is not None and aqi_val > 100:
                    color = "yellow"

                if current_color is None:
                    current_color = color
                    current_coords = [pt]
                elif color == current_color:
                    current_coords.append(pt)
                else:
                    current_coords.append(pt)
                    segments.append({"color": current_color, "coordinates": current_coords})
                    current_color = color
                    current_coords = [pt]

            if current_coords:
                segments.append({"color": current_color, "coordinates": current_coords})

            # ── 8. Distance-weighted average route AQI ─────────────
            total_distance_weighted_aqi = 0.0
            total_distance = 0.0
            for idx in range(len(formatted_coords) - 1):
                pt1 = formatted_coords[idx]
                pt2 = formatted_coords[idx + 1]
                d = _haversine_distance(pt1[0], pt1[1], pt2[0], pt2[1])
                if point_aqis[idx] is not None and point_aqis[idx + 1] is not None:
                    seg_aqi = (point_aqis[idx] + point_aqis[idx + 1]) / 2.0
                    total_distance_weighted_aqi += seg_aqi * d
                total_distance += d

            real_aqis = [a for a in point_aqis if a is not None]
            if total_distance > 0 and total_distance_weighted_aqi > 0:
                avg_route_aqi = total_distance_weighted_aqi / total_distance
            elif real_aqis:
                avg_route_aqi = sum(real_aqis) / len(real_aqis)
            else:
                avg_route_aqi = None

            if max_aqi == 0.0:
                max_aqi = avg_route_aqi if avg_route_aqi is not None else 0.0

            exposure_rating = "Low"
            if avg_route_aqi is not None and avg_route_aqi > 200:
                exposure_rating = "High"
            elif avg_route_aqi is not None and avg_route_aqi > 100:
                exposure_rating = "Moderate"

            aqi_data_available = real_aqi_count > 0

            # ── 9. Data Quality & Confidence metrics ───────────────
            fresh_station_count = sum(1 for age in unique_stations_used.values() if age <= 72.0)
            stale_station_count = sum(1 for age in unique_stations_used.values() if age > 72.0)
            average_station_age_hours = (
                sum(unique_stations_used.values()) / len(unique_stations_used)
                if unique_stations_used else None
            )

            # Confidence Level determination
            if not aqi_data_available:
                confidence = "Low"
            else:
                fallback_pct = (fallback_points_count / len(formatted_coords)) * 100.0 if formatted_coords else 100.0
                if fallback_pct < 15.0 and stale_station_count == 0:
                    confidence = "High"
                elif fallback_pct < 50.0 and stale_station_count <= 2:
                    confidence = "Medium"
                else:
                    confidence = "Low"

            # Helper to build station metadata responses
            def make_station_meta(station: Optional[Any], dist: float, status: str, fallback_time: Optional[datetime]) -> Optional[Dict[str, Any]]:
                if status == "fallback":
                    return {
                        "name": "Open-Meteo Fallback",
                        "distance_km": 0.0,
                        "recorded_at": fallback_time or ref_time,
                        "age_hours": 0.0,
                        "data_status": "fallback"
                    }
                elif station:
                    recorded_at = getattr(station, "recorded_at", None)
                    age = _get_age_hours(recorded_at, ref_time)
                    return {
                        "name": getattr(station, "location_name", "Unknown Station"),
                        "distance_km": round(dist, 2),
                        "recorded_at": recorded_at,
                        "age_hours": round(age, 1) if recorded_at else None,
                        "data_status": status
                    }
                return None

            source_station_meta = make_station_meta(source_station, source_dist, source_status, source_fallback_time)
            dest_station_meta = make_station_meta(dest_station, dest_dist, dest_status, dest_fallback_time)

            # ── 10. Resolve city name ──────────────────────────────
            resolved_city = city
            if not resolved_city:
                try:
                    from data_sync.clients.nominatim_client import NominatimGeocoderClient
                    geocoder = NominatimGeocoderClient()
                    resolved_city = await geocoder.reverse_geocode_city(start_lat, start_lon)
                except Exception:
                    pass
            if not resolved_city:
                resolved_city = "Unknown Location"

            # ── 11. Performance and Observability Logging ──────────
            elapsed_ms = (time.time() - start_time) * 1000.0
            logger.info(
                "=== ROUTE OPTIMIZATION OBSERVABILITY LOG ===\n"
                "Query coordinates     : Source (%f, %f) -> Dest (%f, %f)\n"
                "Selected Source St    : %s (dist: %s, age: %s, status: %s)\n"
                "Selected Dest St      : %s (dist: %s, age: %s, status: %s)\n"
                "Avg Route AQI         : %s\n"
                "Confidence / Quality  : %s (Fresh: %d, Stale: %d, Fallback: %d)\n"
                "Response Time         : %.2f ms\n"
                "============================================",
                start_lat, start_lon, dest_lat, dest_lon,
                source_station_meta.get("name") if source_station_meta else "None",
                source_station_meta.get("distance_km") if source_station_meta else "None",
                source_station_meta.get("age_hours") if source_station_meta else "None",
                source_status,
                dest_station_meta.get("name") if dest_station_meta else "None",
                dest_station_meta.get("distance_km") if dest_station_meta else "None",
                dest_station_meta.get("age_hours") if dest_station_meta else "None",
                dest_status,
                avg_route_aqi,
                confidence, fresh_station_count, stale_station_count, fallback_points_count,
                elapsed_ms
            )

            # ── 12. Build response ─────────────────────────────────
            return {
                "route_name": "Optimal Route",
                "distance_km": round(distance_meters / 1000.0, 2),
                "estimated_time_mins": round(duration_seconds / 60.0, 2),
                "segments": segments,
                "source_aqi": round(source_aqi, 2) if source_aqi is not None else None,
                "source_dominant_pollutant": source_dom_poll,
                "destination_aqi": round(destination_aqi, 2) if destination_aqi is not None else None,
                "destination_dominant_pollutant": destination_dom_poll,
                "average_route_aqi": round(avg_route_aqi, 2) if avg_route_aqi is not None else None,
                "maximum_aqi": round(max_aqi, 2) if max_aqi > 0 else None,
                "dominant_pollutant": dominant_poll,
                "exposure_rating": exposure_rating,
                "resolved_city": resolved_city,
                "aqi_data_available": aqi_data_available,
                "source_station": source_station_meta,
                "destination_station": dest_station_meta,
                "confidence": confidence,
                "data_quality": {
                    "fresh_station_count": fresh_station_count,
                    "stale_station_count": stale_station_count,
                    "fallback_points": fallback_points_count,
                    "average_station_age_hours": round(average_station_age_hours, 1) if average_station_age_hours is not None else None,
                }
            }

        except Exception as e:
            logger.error("Unexpected error in optimized exposure route: %s", e, exc_info=True)
            raise e
