"""Repository layer encapsulating database access, session transactions, and duplicate checks."""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Set, Tuple
from sqlalchemy.orm import Session

from database.models.aqi_data import AQIData
from database.schemas.aqi_data import AQIDataValidate
from api_layer.logging import get_logger

logger = get_logger(__name__)


class DataSyncRepository:
    """Manages all database read and write operations for the ingestion sync workflow."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def get_duplicate_cache(self) -> Set[Tuple[str, datetime]]:
        """Load unique records from database to prevent duplicates (last 48 hours)."""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=48)
        existing_records = (
            self.db.query(AQIData.location_name, AQIData.recorded_at)
            .filter(AQIData.recorded_at >= cutoff.replace(tzinfo=None))
            .all()
        )
        # return set of (location_name, recorded_at_naive) tuples
        return {
            (
                rec.location_name,
                rec.recorded_at.replace(tzinfo=None) if rec.recorded_at.tzinfo else rec.recorded_at
            )
            for rec in existing_records
            if rec.location_name and rec.recorded_at
        }

    def save_record(self, validated_data: AQIDataValidate) -> AQIData:
        """Convert validated Pydantic schema into database record, save, and commit."""
        # Normalize recorded_at to timezone-naive UTC for DB and cache consistency
        recorded_at_naive = validated_data.recorded_at
        if recorded_at_naive.tzinfo:
            recorded_at_naive = recorded_at_naive.astimezone(timezone.utc).replace(tzinfo=None)

        db_record = AQIData(
            city=validated_data.city,
            location_name=validated_data.location_name,
            latitude=validated_data.latitude,
            longitude=validated_data.longitude,
            pm25=validated_data.pm25,
            pm10=validated_data.pm10,
            no2=validated_data.no2,
            o3=validated_data.o3,
            co=validated_data.co,
            so2=validated_data.so2,
            temperature=validated_data.temperature,
            humidity=validated_data.humidity,
            wind_speed=validated_data.wind_speed,
            wind_direction=validated_data.wind_direction,
            precipitation=validated_data.precipitation,
            pressure=validated_data.pressure,
            recorded_at=recorded_at_naive,
            aqi=validated_data.aqi,
            aqi_category=validated_data.aqi_category,
            dominant_pollutant=validated_data.dominant_pollutant,
        )
        self.db.add(db_record)
        self.db.flush()
        return db_record

    def rollback(self) -> None:
        """Roll back current database session transaction."""
        self.db.rollback()
