
"""Service coordinating telemetry data synchronization from OpenAQ and Open-Meteo into the database."""

from __future__ import annotations
from typing import Optional

import time
import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, List
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from pydantic import ValidationError

from api_layer.logging import get_logger
from data_sync.clients.openaq_client import OpenAQClient
from data_sync.clients.openmeteo_weather_client import OpenMeteoWeatherClient as OpenMeteoClient
from data_sync.clients.nominatim_client import NominatimGeocoderClient
from data_sync.data_processor import DataProcessor
from data_sync.repository import DataSyncRepository

logger = get_logger(__name__)


class POCSyncService:
    """Orchestrates telemetry extraction, verification, processing, and database persistence workflows."""

    def __init__(self, db: Session) -> None:
        self.repository = DataSyncRepository(db)
        self.openaq_client = OpenAQClient()
        self.meteo_client = OpenMeteoClient()
        self.geocoder_client = NominatimGeocoderClient()

    async def reverse_geocode_city(self, lat: float, lon: float) -> Optional[str]:
        """Expose geocoding lookup directly for coordination purposes."""
        return await self.geocoder_client.reverse_geocode_city(lat, lon)

    async def sync_openaq_test(self, target_records: int = 100, batch_size: int = 20) -> dict[str, Any]:
        """Fetch multiple locations and latest measurements, validating and deduplicating up to target_records."""
        start_time = time.time()
        countries_id = 9  # India

        # 1. Load duplicate caching
        logger.info("Loading existing database records for duplicate prevention cache...")
        duplicate_cache = self.repository.get_duplicate_cache()
        logger.info("Loaded %d unique records into duplicate check cache (last 48 hours).", len(duplicate_cache))
        # Release the implicit read transaction so no DB connection is held
        # open while we make potentially many slow network requests below.
        self.repository.db.rollback()

        # Counters & stats tracking
        api_requests_count = 0
        fetched_count = 0
        valid_count = 0
        invalid_count = 0
        duplicate_count = 0
        stored_count = 0
        failed_count = 0
        resolved_via_parser_count = 0
        resolved_via_nominatim_count = 0

        cities_collected = set()
        city_distribution = {}
        pm25_populated = 0
        pm10_populated = 0
        no2_populated = 0
        o3_populated = 0

        page = 1
        source_exhausted = False
        stored_records = []

        while stored_count < target_records and not source_exhausted:
            logger.info("OpenAQ request started (page %d, batch_size %d)", page, batch_size)
            try:
                raw_locations = await self.openaq_client.fetch_locations(
                    countries_id=countries_id, limit=batch_size, page=page, order_by="id", sort_order="desc"
                )
                api_requests_count += 1
                logger.info("OpenAQ request successful")
            except Exception as e:
                logger.error("OpenAQ request failed on page %d: %s", page, str(e))
                source_exhausted = True
                break

            results = raw_locations.get("results", [])
            if not results:
                logger.info("No more locations returned by OpenAQ API. Source data exhausted.")
                source_exhausted = True
                break

            # 1. Early Duplicate Filtering & Candidate Selection
            candidates = []
            for raw_loc in results:
                if not raw_loc:
                    continue
                location_name = raw_loc.get("name") or "Unknown Station"
                
                # Safe nested dict lookup for datetimeLast and datetime
                dt_last = raw_loc.get("datetimeLast") or {}
                dt_normal = raw_loc.get("datetime") or {}
                last_updated_str = dt_last.get("utc") or dt_normal.get("last")
                
                is_duplicate = False
                
                if last_updated_str:
                    try:
                        # Parse OpenAQ ISO timestamp
                        recorded_at = datetime.fromisoformat(last_updated_str.replace("Z", "+00:00"))
                        recorded_at_naive = recorded_at.astimezone(timezone.utc).replace(tzinfo=None)
                        dup_key = (location_name, recorded_at_naive)
                        
                        if dup_key in duplicate_cache:
                            logger.info("Early duplicate skip: %s at %s", location_name, recorded_at_naive)
                            duplicate_count += 1
                            is_duplicate = True
                    except Exception as ex:
                        logger.warning("Failed parsing early timestamp for location %s: %s", location_name, str(ex))
                
                if not is_duplicate:
                    candidates.append(raw_loc)
            
            # 2. Batch Weather Retrieval for Non-Duplicate Candidates
            weather_by_coords = {}
            coords_to_fetch = []
            for cand in candidates:
                coords = cand.get("coordinates") or {}
                lat = coords.get("latitude")
                lon = coords.get("longitude")
                if lat is not None and lon is not None:
                    coords_to_fetch.append((lat, lon))
            
            if coords_to_fetch:
                try:
                    lats = [c[0] for c in coords_to_fetch]
                    lons = [c[1] for c in coords_to_fetch]
                    logger.info("Fetching batch weather from Open-Meteo for %d locations", len(coords_to_fetch))
                    weather_results = await self.meteo_client.fetch_batch_current_weather(lats, lons)
                    api_requests_count += 1
                    for idx, w_res in enumerate(weather_results):
                        lat_key = round(coords_to_fetch[idx][0], 5)
                        lon_key = round(coords_to_fetch[idx][1], 5)
                        weather_by_coords[(lat_key, lon_key)] = w_res
                except TypeError as t_err:
                    logger.warning("Batch weather fetch raised TypeError (likely MagicMock): %s. Falling back to sequential queries.", str(t_err))
                    try:
                        for lat, lon in coords_to_fetch:
                            w_res = await self.meteo_client.fetch_current_weather(lat, lon)
                            api_requests_count += 1
                            lat_key = round(lat, 5)
                            lon_key = round(lon, 5)
                            weather_by_coords[(lat_key, lon_key)] = w_res
                    except Exception as w_err_inner:
                        logger.warning("Failed sequential weather fallback: %s", str(w_err_inner))
                except Exception as w_err:
                    logger.warning("Failed to fetch batch weather: %s", str(w_err))

            # 3. Process Non-Duplicate Candidates Sequential Loop (Rate limited measurements fetches)
            for raw_loc in candidates:
                if stored_count >= target_records:
                    break

                location_id = raw_loc.get("id")
                location_name = raw_loc.get("name") or "Unknown Station"
                coordinates = raw_loc.get("coordinates") or {}
                latitude = coordinates.get("latitude")
                longitude = coordinates.get("longitude")

                # Resolve City via Hybrid Resolution Strategy
                from data_sync.data_processor import extract_city_from_name
                city = raw_loc.get("locality") or (raw_loc.get("city", {}) or {}).get("name")
                
                if not city or city.lower() == "unknown":
                    parsed = extract_city_from_name(location_name)
                    if parsed and parsed.lower() != "unknown":
                        city = parsed
                        resolved_via_parser_count += 1
                    else:
                        resolved_city = None
                        if latitude is not None and longitude is not None:
                            resolved_city = await self.geocoder_client.reverse_geocode_city(latitude, longitude)
                        if resolved_city:
                            city = resolved_city
                            resolved_via_nominatim_count += 1
                        else:
                            city = "Unknown"
                else:
                    resolved_via_parser_count += 1

                # Parse Sensor maps via DataProcessor
                sensor_map = DataProcessor.parse_sensor_map(raw_loc)

                try:
                    # Pace requests to respect OpenAQ rate limits (60 requests/minute)
                    await asyncio.sleep(1.0)

                    # Fetch latest measurements for this location
                    logger.info("Fetching measurements for location %s (ID: %s)", location_name, location_id)
                    raw_meas = await self.openaq_client.fetch_latest_measurements(location_id)
                    api_requests_count += 1
                    
                    meas_results = raw_meas.get("results", [])
                    fetched_count += 1  # processed one location candidate

                    # Process pollutant readings via DataProcessor
                    pollutants, recorded_at = DataProcessor.process_measurements(meas_results, sensor_map)

                    # Extract current weather from batch results dictionary
                    weather_res = {}
                    if latitude is not None and longitude is not None:
                        lat_key = round(latitude, 5)
                        lon_key = round(longitude, 5)
                        weather_res = weather_by_coords.get((lat_key, lon_key), {})
                    
                    weather = DataProcessor.merge_weather(pollutants, weather_res)

                    # Validate record via DataProcessor
                    validated_data = DataProcessor.validate_record(
                        city=city,
                        location_name=location_name,
                        latitude=latitude,
                        longitude=longitude,
                        pollutants=pollutants,
                        weather=weather,
                        recorded_at=recorded_at
                    )
                    valid_count += 1

                    # Normalise recorded_at for duplicate lookups
                    recorded_at_naive = validated_data.recorded_at
                    if recorded_at_naive.tzinfo:
                        recorded_at_naive = recorded_at_naive.astimezone(timezone.utc).replace(tzinfo=None)

                    # Late Duplicate Check
                    dup_key = (validated_data.location_name, recorded_at_naive)
                    if dup_key in duplicate_cache:
                        logger.info("Late duplicate record skipped: location_name=%s, recorded_at=%s", validated_data.location_name, validated_data.recorded_at)
                        duplicate_count += 1
                        continue

                    # Save using Database Repository with nested transaction (savepoint)
                    try:
                        with self.repository.db.begin_nested():
                            self.repository.save_record(validated_data)
                    except IntegrityError:
                        # DB-level unique constraint violation: duplicate record
                        # arrived despite in-memory cache (e.g. concurrent run
                        # or server restart).  Treat as a duplicate skip.
                        logger.info(
                            "DB integrity duplicate skipped: location_name=%s, recorded_at=%s",
                            validated_data.location_name, validated_data.recorded_at
                        )
                        duplicate_count += 1
                        continue
                    
                    stored_records.append(validated_data)

                    # Add to cache to prevent duplicates during the same run
                    duplicate_cache.add(dup_key)
                    stored_count += 1

                    # Track metrics
                    cities_collected.add(validated_data.city)
                    city_distribution[validated_data.city] = city_distribution.get(validated_data.city, 0) + 1
                    if validated_data.pm25 is not None:
                        pm25_populated += 1
                    if validated_data.pm10 is not None:
                        pm10_populated += 1
                    if validated_data.no2 is not None:
                        no2_populated += 1
                    if validated_data.o3 is not None:
                        o3_populated += 1

                except (ValidationError, ValueError, TypeError) as val_err:
                    logger.warning("Record validation failed for location %s: %s", location_id, str(val_err))
                    invalid_count += 1
                    failed_count += 1
                except Exception as e:
                    logger.error("Error processing/storing location %s: %s", location_id, str(e))
                    failed_count += 1

            if len(results) < batch_size and len(results) < 100:
                logger.info("Results on page %d was less than page limit. Source data exhausted.", page)
                source_exhausted = True
                break

            page += 1

        # Commit the transaction once at the end of the entire ingestion run
        try:
            self.repository.db.commit()
            
            pass
        except Exception as commit_err:
            logger.error("Final ingestion commit failed: %s", str(commit_err))
            self.repository.rollback()

        # Calculate execution duration
        execution_time = time.time() - start_time

        # Logging Summary
        logger.info("=== INGESTION EXECUTION LOGS ===")
        logger.info("Total API requests made        : %d", api_requests_count)
        logger.info("Total records fetched          : %d", fetched_count)
        logger.info("Valid records                  : %d", valid_count)
        logger.info("Invalid records                : %d", invalid_count)
        logger.info("Duplicate records skipped      : %d", duplicate_count)
        logger.info("Successfully stored records    : %d", stored_count)
        logger.info("Execution time                 : %.2f seconds", execution_time)

        logger.info("=== CITY DISTRIBUTION SUMMARY ===")
        logger.info("City Distribution:")
        for city, count in sorted(city_distribution.items(), key=lambda x: x[1], reverse=True):
            logger.info("%-15s: %d records", city, count)

        logger.info("=== DATA QUALITY VERIFICATION ===")
        logger.info("1. Total records stored        : %d", stored_count)
        logger.info("2. Number of unique cities     : %d", len(cities_collected))
        logger.info("3. Number of records with:")
        logger.info("   - pm25 populated            : %d", pm25_populated)
        logger.info("   - pm10 populated            : %d", pm10_populated)
        logger.info("   - no2 populated             : %d", no2_populated)
        logger.info("   - o3 populated              : %d", o3_populated)
        logger.info("=================================")
        
        logger.info("=== HYBRID RESOLUTION METRICS ===")
        total_resolved = resolved_via_parser_count + resolved_via_nominatim_count
        logger.info("Total locations processed      : %d", total_resolved)
        logger.info("Resolved via local parser      : %d", resolved_via_parser_count)
        logger.info("Resolved via Nominatim fallback: %d", resolved_via_nominatim_count)
        if total_resolved > 0:
            logger.info("Parser success rate            : %.1f%%", (resolved_via_parser_count / total_resolved) * 100)

        return {
            "target": target_records,
            "fetched": fetched_count,
            "valid": valid_count,
            "duplicates": duplicate_count,
            "stored": stored_count,
            "failed": failed_count,
            "execution_time_seconds": round(execution_time, 2),
            "unique_cities": len(cities_collected),
            "cities_collected": sorted(list(cities_collected)),
            "resolved_via_parser": resolved_via_parser_count,
            "resolved_via_nominatim": resolved_via_nominatim_count,
        }
