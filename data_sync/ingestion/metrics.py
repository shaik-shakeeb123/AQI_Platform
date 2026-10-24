"""Structured metrics collection for an ingestion run."""

from __future__ import annotations
import time
from dataclasses import dataclass
from typing import Any

@dataclass
class IngestionMetrics:
    """Collects counters and timings for a single ingestion run."""
    # Location metrics
    locations_examined: int = 0
    locations_attempted: int = 0
    locations_skipped: int = 0

    # Record metrics
    records_fetched: int = 0
    records_validated: int = 0
    records_rejected: int = 0
    records_stored: int = 0
    duplicates_skipped: int = 0

    # API metrics
    openaq_requests: int = 0
    openaq_retries: int = 0
    openaq_rate_limits: int = 0
    openaq_errors: int = 0
    nominatim_requests: int = 0
    openmeteo_requests: int = 0

    # Extended Observability
    requests_admitted: int = 0
    requests_completed: int = 0
    requests_delayed_by_rate_limiter: int = 0
    rate_limit_pauses: int = 0
    hourly_budget_pauses: int = 0
    count_429: int = 0
    count_401: int = 0
    count_403: int = 0
    count_5xx: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Convert metrics to dictionary for database insertion."""
        return {
            "locations_examined": self.locations_examined,
            "locations_attempted": self.locations_attempted,
            "locations_skipped": self.locations_skipped,
            "records_fetched": self.records_fetched,
            "records_validated": self.records_validated,
            "records_rejected": self.records_rejected,
            "records_stored": self.records_stored,
            "duplicates_skipped": self.duplicates_skipped,
            "openaq_requests": self.openaq_requests,
            "openaq_retries": self.openaq_retries,
            "openaq_rate_limits": self.openaq_rate_limits,
            "openaq_errors": self.openaq_errors,
            "nominatim_requests": self.nominatim_requests,
            "openmeteo_requests": self.openmeteo_requests,
        }

    def summarize(self) -> str:
        """Return a human-readable summary of the metrics."""
        return (
            f"Locs(examined={self.locations_examined}, attempted={self.locations_attempted}, skipped={self.locations_skipped}) | "
            f"Recs(fetched={self.records_fetched}, stored={self.records_stored}, rejected={self.records_rejected}, dups={self.duplicates_skipped}) | "
            f"Gov(admit={self.requests_admitted}, compl={self.requests_completed}, 429={self.count_429}, paused={self.rate_limit_pauses}) | "
            f"API(retries={self.openaq_retries}, errs={self.openaq_errors}, nom={self.nominatim_requests}, meteo={self.openmeteo_requests})"
        )
