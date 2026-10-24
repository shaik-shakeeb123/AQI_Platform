from typing import Optional, Any
from sqlalchemy.orm import Session
from sqlalchemy import func
from database.models.aqi_data import AQIData

class DiagnosticsRepository:
    """Repository handling database status checks for system diagnostics."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def get_latest_record(self) -> Optional[AQIData]:
        """Fetch the single latest telemetry record by recorded time."""
        return (
            self.db.query(AQIData)
            .order_by(AQIData.recorded_at.desc())
            .first()
        )

    def get_latest_ingestion_run(self) -> Optional[Any]:
        """Fetch the most recent ingestion run record for diagnostics, if available."""
        try:
            from data_sync.ingestion.models import IngestionRun
            return (
                self.db.query(IngestionRun)
                .order_by(IngestionRun.started_at.desc())
                .first()
            )
        except Exception:
            return None

    def execute_ping(self) -> None:
        """Run a simple SELECT query to confirm connectivity."""
        self.db.execute(func.now())
