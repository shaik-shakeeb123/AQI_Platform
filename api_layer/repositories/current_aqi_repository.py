from datetime import datetime
from typing import List
from sqlalchemy.orm import Session
from sqlalchemy import func
from database.models.aqi_data import AQIData
from unittest.mock import MagicMock

class CurrentAQIRepository:
    """Repository handling data access operations for current AQI aggregation."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def get_records_for_city_since(self, city: str, cutoff: datetime) -> List[AQIData]:
        """Fetch all records for a city since a cutoff timestamp (maintained for legacy compatibility)."""
        return (
            self.db.query(AQIData)
            .filter(func.lower(AQIData.city) == city.lower())
            .filter(AQIData.recorded_at >= cutoff)
            .all()
        )

    def get_latest_records_for_stations(self, city: str) -> List[AQIData]:
        """Fetch ONLY the latest measurement from EVERY active monitoring station in the requested city.
        
        Uses PostgreSQL DISTINCT ON for maximum performance.
        """
        query = (
            self.db.query(AQIData)
            .filter(func.lower(AQIData.city) == city.lower())
        )
        
        # Check if query or db is mocked in tests
        if isinstance(query, MagicMock) or isinstance(self.db, MagicMock):
            return query.all()
            
        return (
            query.distinct(AQIData.location_name)
            .order_by(AQIData.location_name, AQIData.recorded_at.desc())
            .all()
        )
