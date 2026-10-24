"""Ingestion planner for prioritizing and scheduling location polling."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import select, and_, or_, func, update

from data_sync.ingestion.models import IngestionLocation, IngestionState

class IngestionPlanner:
    """Plans which locations to poll for measurements based on activity."""

    def __init__(
        self, 
        db: Session, 
        provider: str, 
        overlap_minutes: int = 60
    ) -> None:
        self.db = db
        self.provider = provider
        self.overlap_minutes = overlap_minutes

    def get_watermark(self, resource: str, scope: str = "all") -> datetime | None:
        """Get the global watermark for a resource."""
        state = self.db.scalar(
            select(IngestionState).where(
                and_(
                    IngestionState.provider == self.provider,
                    IngestionState.resource == resource,
                    IngestionState.scope == scope
                )
            )
        )
        return state.watermark if state else None
        
    def advance_watermark(self, resource: str, scope: str, new_watermark: datetime) -> None:
        """Advance the watermark if the new watermark is strictly greater."""
        state = self.db.scalar(
            select(IngestionState).where(
                and_(
                    IngestionState.provider == self.provider,
                    IngestionState.resource == resource,
                    IngestionState.scope == scope
                )
            ).with_for_update()
        )
        
        if not state:
            state = IngestionState(
                provider=self.provider,
                resource=resource,
                scope=scope,
                watermark=new_watermark,
                status="SUCCESS"
            )
            self.db.add(state)
        elif not state.watermark or new_watermark > state.watermark:
            state.watermark = new_watermark
            state.status = "SUCCESS"
            
        self.db.flush()

    def plan_measurement_ingestion(self, limit: int | None = None) -> List[IngestionLocation]:
        """Select locations to poll based on an adaptive frequency strategy.
        
        Active locations (updated < 24h ago) are polled every run.
        Inactive locations (updated 1d-7d ago) are polled if they haven't been checked in 6 hours.
        Dead locations (updated > 7d ago) are not polled by measurement ingestion.
        """
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        
        # Base rate limit to avoid hammering the same station on back-to-back runs (e.g. 15 mins)
        recently_checked = now - timedelta(minutes=15)
        # Fallback to check active stations at least once a day even if metadata seems stale
        daily_check = now - timedelta(hours=24)
        
        stmt = (
            select(IngestionLocation)
            .where(
                and_(
                    IngestionLocation.provider == self.provider,
                    IngestionLocation.is_active == True,
                    or_(
                        IngestionLocation.last_synced_at == None,
                        IngestionLocation.last_synced_at <= recently_checked,
                    ),
                    or_(
                        # Never successfully ingested
                        IngestionLocation.last_successful_ingestion_at == None,
                        # Metadata indicates newer data is available
                        IngestionLocation.provider_datetime_last > IngestionLocation.last_successful_ingestion_at,
                        # Fallback to check periodically just in case
                        IngestionLocation.last_synced_at <= daily_check,
                    ),
                )
            )
            .order_by(
                IngestionLocation.last_synced_at.asc().nullsfirst(),
                IngestionLocation.provider_location_id.asc(),
            )
        )
        
        if limit is None:
            from api_layer.config import get_settings
            raw_limit = get_settings().SCHEDULED_BATCH_SIZE
        else:
            raw_limit = limit

        if not isinstance(raw_limit, int) or isinstance(raw_limit, bool) or raw_limit <= 0:
            raise ValueError(
                f"Invalid measurement ingestion batch limit: {raw_limit!r}. "
                "Limit must be a positive non-zero integer."
            )

        stmt = stmt.limit(raw_limit)
        locations = self.db.scalars(stmt).all()
        return list(locations)
