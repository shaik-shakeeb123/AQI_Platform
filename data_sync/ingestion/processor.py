"""Measurement normalization, enrichment, and persistence."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from api_layer.logging import get_logger
from data_sync.ingestion.metrics import IngestionMetrics
from data_sync.ingestion.models import IngestionLocation
from data_sync.data_processor import (
    DataProcessor, calculate_overall_aqi,
    extract_city_from_name, extract_measurement_datetime
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
    ) -> None:
        self.db = db
        self.metrics = metrics
        self.geocoder = geocoder
        self.weather_client = weather_client

    async def resolve_city_for_location(self, loc: IngestionLocation) -> str | None:
        """Resolve city using regex parser, then Nominatim, and cache it."""
        if loc.city:
            return loc.city
            
        # Try local parser
        parsed = extract_city_from_name(loc.location_name)
        if parsed:
            loc.city = parsed
            loc.city_resolution_source = "LOCAL_PARSER"
            return parsed
            
        # Fallback to Nominatim
        if loc.latitude is not None and loc.longitude is not None:
            self.metrics.nominatim_requests += 1
            city = await self.geocoder.reverse_geocode_city(loc.latitude, loc.longitude)
            if city:
                loc.city = city
                loc.city_resolution_source = "NOMINATIM"
                return city
                
        return None

    async def process_and_store(
        self, 
        loc: IngestionLocation, 
        raw_measurements: list[dict[str, Any]]
    ) -> Tuple[list[AQIData], Optional[datetime]]:
        """Process a location's measurements and return records to store."""
        if not raw_measurements:
            self.metrics.records_rejected += 1
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

        # Process measurements using legacy rules
        # Mocking the legacy sensor map since v3 /latest doesn't strictly need it if we parse directly
        # But we must adhere to `process_measurements` signature
        
        # OpenAQ v3 /latest payload structure for a location typically contains a `results` array of measurements
        # Let's map it into the format expected by process_measurements
        sensors_mock = {} 
        for m in raw_measurements:
            param = m.get("parameter", {}).get("name", "")
            if not param:
                continue
            unit = m.get("parameter", {}).get("units", "")
            sensor_id = m.get("sensorsId") or m.get("sensorId") or m.get("id")
            if sensor_id:
                sensors_mock[sensor_id] = (param.lower(), unit)

        try:
            grouped_records = DataProcessor.process_measurements(raw_measurements, sensors_mock)
        except ValueError:
            self.metrics.records_rejected += 1
            return [], None

        # Resolve city once
        city = await self.resolve_city_for_location(loc)

        # We will track if at least one insert succeeds to mark the station as successfully ingested
        any_success = False
        latest_stored_time = loc.last_successful_ingestion_at
        records_to_insert = []

        for processed_pollutants, processor_time in grouped_records:
            # If data is not newer than what we have, skip
            if loc.last_successful_ingestion_at and processor_time <= loc.last_successful_ingestion_at:
                self.metrics.duplicates_skipped += 1
                continue
                
            # Fetch weather enrichment (only if we don't already have it cached, but for simplicity fetch for latest or all)
            weather_data = {
                "wind_speed": None, "wind_direction": None, "precipitation": None, "pressure": None,
                "temperature": processed_pollutants.get("temperature"),
                "humidity": processed_pollutants.get("humidity")
            }
            if loc.latitude and loc.longitude:
                try:
                    self.metrics.openmeteo_requests += 1
                    weather_res = await self.weather_client.fetch_current_weather(loc.latitude, loc.longitude)
                    weather_data = DataProcessor.merge_weather(processed_pollutants, weather_res)
                except Exception as e:
                    logger.warning("Weather fetch failed for %s: %s", loc.location_name, str(e))

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
