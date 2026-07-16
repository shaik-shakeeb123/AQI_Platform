from typing import List
from sqlalchemy.orm import Session
from sqlalchemy import func
from database.models.aqi_data import AQIData

class PredictionRepository:
    """Repository handling data access operations for AQI prediction inputs."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def get_recent_history_for_city(self, city: str, limit: int = 24) -> List[AQIData]:
        """Fetch the latest records for a city up to limit (chronological desc)."""
        return (
            self.db.query(AQIData)
            .filter(func.lower(AQIData.city) == city.lower())
            .order_by(AQIData.recorded_at.desc())
            .limit(limit)
            .all()
        )
