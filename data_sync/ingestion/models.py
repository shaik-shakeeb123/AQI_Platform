"""SQLAlchemy ORM models for ingestion infrastructure.

Three tables power the new ingestion pipeline:

* ``ingestion_state``     – persistent watermark / checkpoint per provider.
* ``ingestion_runs``      – auditable record of every execution.
* ``ingestion_locations`` – cached provider location catalog so Nominatim
                            is called at most once per station.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean, DateTime, Float, Index, Integer, String, Text,
    UniqueConstraint, func,
)
from sqlalchemy.orm import Mapped, mapped_column

from database.connection import Base


# ---------------------------------------------------------------------------
# Ingestion state / watermark
# ---------------------------------------------------------------------------

class IngestionState(Base):
    """Persistent watermark for incremental ingestion.

    One row per ``(provider, resource, scope)`` triple.  ``watermark`` is the
    UTC timestamp up to which data has been successfully ingested.
    """

    __tablename__ = "ingestion_state"
    __table_args__ = (
        UniqueConstraint(
            "provider", "resource", "scope",
            name="uq_ingestion_state_prov_res_scope",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    resource: Mapped[str] = mapped_column(String(50), nullable=False)
    scope: Mapped[str] = mapped_column(String(50), nullable=False)
    watermark: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default="IDLE",
    )
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now(),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(),
    )

    def __repr__(self) -> str:
        return (
            f"<IngestionState(provider={self.provider!r}, resource={self.resource!r}, "
            f"scope={self.scope!r}, watermark={self.watermark})>"
        )


# ---------------------------------------------------------------------------
# Ingestion run history
# ---------------------------------------------------------------------------

class IngestionRun(Base):
    """Auditable record of a single ingestion execution."""

    __tablename__ = "ingestion_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(36), nullable=False, unique=True)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    mode: Mapped[str] = mapped_column(String(30), nullable=False)        # SCHEDULED / BACKFILL / MANUAL
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default="RUNNING",
    )
    dry_run: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    started_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(),
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Watermark tracking
    watermark_before: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    watermark_after: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Location counters
    locations_examined: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    locations_attempted: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    locations_skipped: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    # Record counters
    records_fetched: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    records_validated: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    records_rejected: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    records_stored: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    duplicates_skipped: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    # Provider request counters
    openaq_requests: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    openaq_retries: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    openaq_rate_limits: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    openaq_errors: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    nominatim_requests: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    openmeteo_requests: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    # Timing
    execution_seconds: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<IngestionRun(run_id={self.run_id!r}, status={self.status!r}, "
            f"stored={self.records_stored})>"
        )


# ---------------------------------------------------------------------------
# Location catalog
# ---------------------------------------------------------------------------

class IngestionLocation(Base):
    """Persistent catalog of provider monitoring stations.

    City resolution results are cached here so Nominatim is called at most
    once per physical station across all future runs.
    """

    __tablename__ = "ingestion_locations"
    __table_args__ = (
        UniqueConstraint(
            "provider", "provider_location_id",
            name="uq_ingestion_loc_prov_locid",
        ),
        Index("ix_ingestion_loc_datetime_last", "provider_datetime_last"),
        Index("ix_ingestion_loc_planner", "provider", "is_active", "last_synced_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    provider_location_id: Mapped[int] = mapped_column(Integer, nullable=False)
    location_name: Mapped[str] = mapped_column(String(200), nullable=False)
    latitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    longitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Resolved city metadata (cached to avoid repeated Nominatim)
    city: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    state: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    country: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    country_code: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    city_resolution_source: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    provider_datetime_first: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    provider_datetime_last: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_successful_ingestion_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    sensors_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    last_synced_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now(),
    )

    def __repr__(self) -> str:
        return (
            f"<IngestionLocation(provider={self.provider!r}, "
            f"id={self.provider_location_id}, name={self.location_name!r}, "
            f"city={self.city!r})>"
        )
