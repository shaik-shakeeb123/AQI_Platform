from typing import List, Optional
from database.models.aqi_data import AQIData
from api_layer.repositories.history_repository import HistoryRepository

class HistoryService:
    """Service orchestrating business logic for fetching telemetry logs history."""

    def __init__(self, repository: HistoryRepository) -> None:
        self.repository = repository

    def get_history(self, skip: int, limit: int, city: Optional[str] = None, sort: str = "desc") -> List[AQIData]:
        """Validate parameters and delegate history query to the repository."""
        return self.repository.get_history(skip=skip, limit=limit, city=city, sort=sort)
