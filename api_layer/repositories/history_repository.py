from typing import List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import func
from database.models.aqi_data import AQIData

class HistoryRepository:
    """Repository handling data access operations for historical AQI telemetry."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def get_history(
        self,
        skip: int,
        limit: int,
        city: Optional[str] = None,
        sort: str = "desc"
    ) -> List[AQIData]:
        """Fetch historical records filtered by city, sorted, and paginated."""
        if sort.lower() == "asc":
            query = self.db.query(AQIData).order_by(AQIData.recorded_at.asc())
        else:
            query = self.db.query(AQIData).order_by(AQIData.recorded_at.desc())
        
        if city:
            query = query.filter(func.lower(AQIData.city) == city.lower())
            
        return query.offset(skip).limit(limit).all()
