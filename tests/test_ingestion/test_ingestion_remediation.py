"""Offline unit and regression tests for ingestion remediation.

Covers:
1. OpenAQ v3 timestamp handling (various formats, missing/malformed formats).
2. Location scheduling fairness (nulls first, stalest next, deterministic tie-breakers, 15m rule).
3. Metric consistency (locations_skipped invariant, record counter units).
4. Safe isolated database fixtures (zero production DB writes).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database.connection import Base
import data_sync.ingestion.models  # noqa: F401
import database.models.aqi_data    # noqa: F401
from data_sync.data_processor import extract_measurement_datetime, DataProcessor
from data_sync.ingestion.models import IngestionLocation, IngestionRun
from data_sync.ingestion.planner import IngestionPlanner
from data_sync.ingestion.processor import IngestionProcessor
from data_sync.ingestion.metrics import IngestionMetrics
from data_sync.ingestion.coordinator import IngestionCoordinator


# ============================================================================
# ISOLATED IN-MEMORY DATABASE FIXTURE (ZERO REMOTE ACCESS)
# ============================================================================

# ============================================================================
# 1. OPENAQ V3 TIMESTAMP EXTRACTION TESTS
# ============================================================================

def test_extract_timestamp_openaq_v3_datetime_object():
    """Verify OpenAQ v3 standard datetime.utc object extraction."""
    payload = {"datetime": {"utc": "2026-03-15T08:30:00Z", "local": "2026-03-15T14:00:00+05:30"}}
    extracted = extract_measurement_datetime(payload)
    assert extracted == datetime(2026, 3, 15, 8, 30, 0)


def test_extract_timestamp_openaq_v3_datetime_string():
    """Verify OpenAQ v3 direct ISO string datetime extraction."""
    payload = {"datetime": "2026-03-15T08:30:00+00:00"}
    extracted = extract_measurement_datetime(payload)
    assert extracted == datetime(2026, 3, 15, 8, 30, 0)


def test_extract_timestamp_period_datetime_to():
    """Verify OpenAQ v3 period.datetimeTo.utc extraction."""
    payload = {"period": {"datetimeTo": {"utc": "2026-03-15T09:00:00Z"}}}
    extracted = extract_measurement_datetime(payload)
    assert extracted == datetime(2026, 3, 15, 9, 0, 0)


def test_extract_timestamp_period_datetime_to_string():
    """Verify OpenAQ v3 period.datetimeTo direct string extraction."""
    payload = {"period": {"datetimeTo": "2026-03-15T09:00:00Z"}}
    extracted = extract_measurement_datetime(payload)
    assert extracted == datetime(2026, 3, 15, 9, 0, 0)


def test_extract_timestamp_period_datetime_from_fallback():
    """Verify fallback to period.datetimeFrom when datetimeTo is absent."""
    payload = {"period": {"datetimeFrom": {"utc": "2026-03-15T08:00:00Z"}}}
    extracted = extract_measurement_datetime(payload)
    assert extracted == datetime(2026, 3, 15, 8, 0, 0)


def test_extract_timestamp_v2_date_utc():
    """Verify legacy OpenAQ v2 date.utc extraction."""
    payload = {"date": {"utc": "2026-03-15T07:15:00Z"}}
    extracted = extract_measurement_datetime(payload)
    assert extracted == datetime(2026, 3, 15, 7, 15, 0)


def test_extract_timestamp_missing_and_malformed_safeguards():
    """Verify missing, empty, or malformed payloads do not raise exceptions."""
    assert extract_measurement_datetime({}) is None
    assert extract_measurement_datetime(None) is None
    assert extract_measurement_datetime("not a dict") is None
    assert extract_measurement_datetime({"period": None, "datetime": None}) is None
    assert extract_measurement_datetime({"datetime": "malformed-timestamp-value"}) is None
    assert extract_measurement_datetime({"period": {"datetimeTo": "not-a-date"}}) is None
    assert extract_measurement_datetime({"date": None}) is None


@pytest.mark.asyncio
async def test_processor_handles_openaq_v3_datetime_payload(in_memory_db):
    """Verify IngestionProcessor accepts OpenAQ v3 datetime.utc payload and stores it."""
    metrics = IngestionMetrics()
    geocoder = MagicMock()
    weather_client = MagicMock()
    weather_client.fetch_current_weather = AsyncMock(return_value={})

    processor = IngestionProcessor(
        db=in_memory_db,
        metrics=metrics,
        geocoder=geocoder,
        weather_client=weather_client,
    )

    loc = IngestionLocation(
        provider="OpenAQ",
        provider_location_id=999,
        location_name="Anand Vihar, Delhi",
        latitude=28.64,
        longitude=77.31,
        is_active=True,
    )

    raw_measurements = [
        {
            "sensorsId": 1,
            "parameter": {"name": "pm25", "units": "µg/m³"},
            "value": 45.0,
            "datetime": {"utc": "2026-04-01T12:00:00Z"},
        },
        {
            "sensorsId": 2,
            "parameter": {"name": "pm10", "units": "µg/m³"},
            "value": 85.0,
            "datetime": {"utc": "2026-04-01T12:00:00Z"},
        },
    ]

    records, latest_time = await processor.process_and_store(loc, raw_measurements)
    assert len(records) == 1
    assert latest_time == datetime(2026, 4, 1, 12, 0, 0)
    assert metrics.records_validated == 1
    assert records[0].pm25 == 45.0
    assert records[0].pm10 == 85.0


@pytest.mark.asyncio
async def test_processor_rejects_missing_timestamp_cleanly(in_memory_db):
    """Verify IngestionProcessor cleanly rejects measurements missing timestamps."""
    metrics = IngestionMetrics()
    processor = IngestionProcessor(
        db=in_memory_db,
        metrics=metrics,
        geocoder=MagicMock(),
        weather_client=MagicMock(),
    )

    loc = IngestionLocation(
        provider="OpenAQ",
        provider_location_id=1001,
        location_name="Station Without Timestamps",
        is_active=True,
    )

    raw_measurements = [
        {"sensorsId": 1, "parameter": {"name": "pm25"}, "value": 30.0}
    ]

    records, latest_time = await processor.process_and_store(loc, raw_measurements)
    assert records == []
    assert latest_time is None
    assert metrics.records_rejected == 1


# ============================================================================
# 2. LOCATION SCHEDULING FAIRNESS TESTS
# ============================================================================

def test_planner_scheduling_fairness_and_ordering(in_memory_db):
    """Verify planner prioritizes nulls first, then stalest, with deterministic tie-breaker."""
    planner = IngestionPlanner(db=in_memory_db, provider="OpenAQ")

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    two_hours_ago = now - timedelta(hours=2)
    one_hour_ago = now - timedelta(hours=1)
    ten_mins_ago = now - timedelta(minutes=10)  # Suppressed by 15-min anti-hammering

    # Setup stations:
    # loc_null_b: null last_synced_at, provider_id=200
    # loc_null_a: null last_synced_at, provider_id=100 (should tie-break first)
    # loc_stale: last_synced_at = 2h ago, provider_id=300
    # loc_recent_eligible: last_synced_at = 1h ago, provider_id=400
    # loc_hammered: last_synced_at = 10m ago, provider_id=500 (should NOT be scheduled)
    # loc_inactive: is_active=False, provider_id=600 (should NOT be scheduled)

    loc_null_b = IngestionLocation(provider="OpenAQ", provider_location_id=200, location_name="Null_B", is_active=True, last_synced_at=None)
    loc_null_a = IngestionLocation(provider="OpenAQ", provider_location_id=100, location_name="Null_A", is_active=True, last_synced_at=None)
    loc_stale = IngestionLocation(provider="OpenAQ", provider_location_id=300, location_name="Stale", is_active=True, last_synced_at=two_hours_ago)
    loc_recent_eligible = IngestionLocation(provider="OpenAQ", provider_location_id=400, location_name="RecentEligible", is_active=True, last_synced_at=one_hour_ago)
    loc_hammered = IngestionLocation(provider="OpenAQ", provider_location_id=500, location_name="Hammered", is_active=True, last_synced_at=ten_mins_ago)
    loc_inactive = IngestionLocation(provider="OpenAQ", provider_location_id=600, location_name="Inactive", is_active=False, last_synced_at=None)

    in_memory_db.add_all([loc_null_b, loc_null_a, loc_stale, loc_recent_eligible, loc_hammered, loc_inactive])
    in_memory_db.commit()

    planned = planner.plan_measurement_ingestion()
    planned_ids = [loc.provider_location_id for loc in planned]

    # Verify:
    # 1. loc_hammered (polled 10m ago) is excluded
    assert 500 not in planned_ids
    # 2. loc_inactive is excluded
    assert 600 not in planned_ids
    # 3. Exact ordering:
    #    - Nulls first, tie-broken by provider_location_id ASC: 100 then 200
    #    - Stalest next (2 hours ago): 300
    #    - Fresher next (1 hour ago): 400
    assert planned_ids == [100, 200, 300, 400]


# ============================================================================
# 3. METRIC CONSISTENCY & INVARIANTS TESTS
# ============================================================================

@pytest.mark.asyncio
async def test_coordinator_locations_skipped_invariant(in_memory_db):
    """Verify locations_skipped is accurately computed when a run is partially executed."""
    coord = IngestionCoordinator(db=in_memory_db, dry_run=False)
    coord.provider = "OpenAQ"

    # Simulate 5 locations planned
    locs = [
        IngestionLocation(provider="OpenAQ", provider_location_id=i, location_name=f"Station_{i}", is_active=True)
        for i in range(1, 6)
    ]
    in_memory_db.add_all(locs)
    in_memory_db.commit()

    coord.planner.plan_measurement_ingestion = MagicMock(return_value=locs)
    coord._acquire_lock = AsyncMock(return_value=True)
    coord._should_run_metadata_sync = AsyncMock(return_value=False)
    coord._check_db_backed_hourly_budget = AsyncMock(return_value=True)

    # Let the worker process 2 locations, then raise an auth error on location 3
    call_count = 0

    async def mock_get_latest(provider_id):
        nonlocal call_count
        call_count += 1
        if call_count > 2:
            from api_layer.exceptions import ExternalAPIException
            raise ExternalAPIException("Simulated 401 auth error", status_code=502, error_code="AUTHENTICATION_FAILED")
        return {"results": [{"parameter": {"name": "pm25"}, "value": 15, "datetime": {"utc": "2026-04-01T12:00:00Z"}}]}

    coord.provider_adapter.get_latest_measurements = AsyncMock(side_effect=mock_get_latest)

    status = await coord.execute()

    assert status == "FAILED"
    # 5 locations were examined
    assert coord.metrics.locations_examined == 5
    # Worker attempted locations until failure halted it
    assert coord.metrics.locations_attempted >= 2
    # The invariant MUST hold: examined == attempted + skipped
    assert coord.metrics.locations_examined == coord.metrics.locations_attempted + coord.metrics.locations_skipped
    assert coord.run_record.locations_skipped == coord.metrics.locations_skipped
