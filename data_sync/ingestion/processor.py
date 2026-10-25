"""Measurement normalization, enrichment, and persistence."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone, timedelta
from typing import Any, Tuple, Optional

from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from api_layer.logging import get_logger
from data_sync.ingestion.metrics import IngestionMetrics
from data_sync.ingestion.models import IngestionLocation
from data_sync.data_processor import (
    DataProcessor, calculate_overall_aqi,
    extract_city_from_name, extract_measurement_datetime,
    parse_and_validate_sensors_json, merge_sensor_maps, lookup_sensor_mapping,
    DEFAULT_WEATHER_FRESHNESS_TOLERANCE, is_contemporaneous
)
from database.models.aqi_data import AQIData
from database.schemas.aqi_data import AQIDataValidate
from data_sync.clients.nominatim_client import NominatimGeocoderClient
from data_sync.clients.openmeteo_weather_client import OpenMeteoWeatherClient

logger = get_logger(__name__)

class IngestionProcessor:
    """Processes raw measurements, enriches them, and idempotently stores them."""

    def __init__(
        self, 
        db: Session, 
        metrics: IngestionMetrics,
        geocoder: NominatimGeocoderClient,
        weather_client: OpenMeteoWeatherClient,
        weather_freshness_tolerance: timedelta = DEFAULT_WEATHER_FRESHNESS_TOLERANCE,
    ) -> None:
        self.db = db
        self.metrics = metrics
        self.geocoder = geocoder
        self.weather_client = weather_client
        self.weather_freshness_tolerance = weather_freshness_tolerance

    async def resolve_city_for_location(self, loc: IngestionLocation) -> str | None:
        """Resolve city using regex parser, then Nominatim, and cache it.
        
        Guarantees that a geocoder network timeout or failure does not crash the
        worker or discard otherwise valid pollutant observations.
        """
        if loc.city:
            return loc.city
            
        # Try local parser first
        parsed = extract_city_from_name(loc.location_name)
        if parsed and parsed.lower() != "unknown":
            loc.city = parsed
            loc.city_resolution_source = "LOCAL_PARSER"
            return parsed
            
        # Fallback to Nominatim with graceful error isolation
        if loc.latitude is not None and loc.longitude is not None:
            try:
                self.metrics.nominatim_requests += 1
                city = await self.geocoder.reverse_geocode_city(loc.latitude, loc.longitude)
                if city:
                    loc.city = city
                    loc.city_resolution_source = "NOMINATIM"
                    return city
            except Exception as e:
                logger.warning(
                    "Reverse geocoding failed for location %d (%s) at (%.4f, %.4f): %s. Falling back to Unknown.",
                    loc.provider_location_id, loc.location_name, loc.latitude, loc.longitude, e
                )
                
        return None

    async def process_and_store(
        self, 
        loc: IngestionLocation, 
        raw_measurements: list[dict[str, Any]]
    ) -> Tuple[list[AQIData], Optional[datetime]]:
        """Process a location's measurements and return records to store."""
        if not raw_measurements:
            # Empty response for this station; no records to validate or reject
            return [], None
            
        # Extract the exact measurement timestamp from the raw payload safely
        latest_meas_time = None
        for m in raw_measurements:
            dt_parsed = extract_measurement_datetime(m)
            if dt_parsed:
                if latest_meas_time is None or dt_parsed > latest_meas_time:
                    latest_meas_time = dt_parsed
                    
        if not latest_meas_time:
            self.metrics.records_rejected += 1
            return [], None

        # If data is not newer than what we have, skip
        if loc.last_successful_ingestion_at and latest_meas_time <= loc.last_successful_ingestion_at:
            self.metrics.duplicates_skipped += 1
            return [], None

        # Build sensor map from cached sensors_json
        sensors_mock = parse_and_validate_sensors_json(loc.sensors_json)

        # Incorporate both str and int keys to guarantee lookup compatibility
        int_keys = {int(k): v for k, v in sensors_mock.items() if k.isdigit()}
        sensors_mock.update(int_keys)

        for m in raw_measurements:
            param_obj = m.get("parameter")
            param_name = ""
            unit = ""
            if isinstance(param_obj, dict):
                param_name = param_obj.get("name", "")
                unit = param_obj.get("units", "")
            elif isinstance(param_obj, str):
                param_name = param_obj
            elif m.get("pollutant"):
                param_name = str(m.get("pollutant"))

            sensor_id = m.get("sensorsId") or m.get("sensorId") or m.get("id")
            if sensor_id is not None and param_name:
                s_key = str(sensor_id).strip()
                p_name_lower = param_name.strip().lower()
                unit_str = str(unit).strip()
                sensors_mock[s_key] = (p_name_lower, unit_str)
                if s_key.isdigit():
                    sensors_mock[int(s_key)] = (p_name_lower, unit_str)

        # If loc did not have sensors_json, but we discovered sensors in raw_measurements, cache them
        if not loc.sensors_json and sensors_mock:
            loc.sensors_json = json.dumps({
                str(k): list(v) for k, v in sensors_mock.items() if isinstance(k, str)
            })

        try:
            grouped_records = DataProcessor.process_measurements(raw_measurements, sensors_mock)
        except ValueError:
            self.metrics.records_rejected += 1
            return [], None

        # Resolve city once (with graceful fallback on geocoding error)
        city = await self.resolve_city_for_location(loc)

        # We will track if at least one insert succeeds to mark the station as successfully ingested
        latest_stored_time = loc.last_successful_ingestion_at
        records_to_insert = []

        for processed_pollutants, processor_time in grouped_records:
            # If data is not newer than what we have, skip
            if loc.last_successful_ingestion_at and processor_time <= loc.last_successful_ingestion_at:
                self.metrics.duplicates_skipped += 1
                continue
                
            # Fetch weather enrichment only for contemporaneous observations.
            # Never attach current real-time weather to historical observations.
            weather_data = {
                "wind_speed": None, "wind_direction": None, "precipitation": None, "pressure": None,
                "temperature": processed_pollutants.get("temperature"),
                "humidity": processed_pollutants.get("humidity")
            }
            if loc.latitude and loc.longitude and is_contemporaneous(processor_time, tolerance=self.weather_freshness_tolerance):
                try:
                    self.metrics.openmeteo_requests += 1
                    weather_res = await self.weather_client.fetch_current_weather(loc.latitude, loc.longitude)
                    weather_data = DataProcessor.merge_weather(processed_pollutants, weather_res)
                except Exception as e:
                    logger.warning("Weather fetch failed for %s: %s", loc.location_name, str(e))
            elif loc.latitude and loc.longitude:
                logger.info(
                    "Skipping current weather enrichment for non-contemporaneous observation (%s) at %s.",
                    processor_time.isoformat() if processor_time else "None", loc.location_name
                )

            # Calculate AQI
            aqi_val, aqi_cat, dom_pol = calculate_overall_aqi(
                pm25=processed_pollutants.get("pm25"),
                pm10=processed_pollutants.get("pm10"),
                no2=processed_pollutants.get("no2"),
                so2=processed_pollutants.get("so2"),
                co=processed_pollutants.get("co"),
                o3=processed_pollutants.get("o3")
            )
            
            # Prepare for validation and insert
            record_dict = {
                "city": city or "Unknown",
                "location_name": loc.location_name,
                "latitude": loc.latitude or 0.0,
                "longitude": loc.longitude or 0.0,
                "recorded_at": processor_time,
                "aqi": aqi_val,
                "aqi_category": aqi_cat,
                "dominant_pollutant": dom_pol,
                **processed_pollutants,
                **weather_data
            }

            try:
                validated = AQIDataValidate(**record_dict)
                self.metrics.records_validated += 1
                
                db_record = AQIData(**validated.model_dump())
                records_to_insert.append(db_record)
                
                if latest_stored_time is None or processor_time > latest_stored_time:
                    latest_stored_time = processor_time
                    
            except Exception as e:
                logger.warning("Validation failed for %s: %s", loc.location_name, str(e))
                self.metrics.records_rejected += 1
                continue
                
        if not records_to_insert:
            return [], None
            
        return records_to_insert, latest_stored_time
