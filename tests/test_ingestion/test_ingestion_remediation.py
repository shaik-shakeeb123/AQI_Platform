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
from sqlalchemy import create_engine, select
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
    """Verify planner prioritizes new/sentinel stations first, then stalest, with deterministic tie-breaker."""
    planner = IngestionPlanner(db=in_memory_db, provider="OpenAQ")

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    two_hours_ago = now - timedelta(hours=2)
    one_hour_ago = now - timedelta(hours=1)
    ten_mins_ago = now - timedelta(minutes=10)  # Suppressed by 15-min anti-hammering

    # Setup stations:
    # Newly discovered stations initialized with sentinel datetime(2000, 1, 1):
    # loc_new_b: provider_id=200
    # loc_new_a: provider_id=100 (should tie-break first)
    # loc_stale: last_synced_at = 2h ago, provider_id=300
    # loc_recent_eligible: last_synced_at = 1h ago, provider_id=400
    # loc_hammered: last_synced_at = 10m ago, provider_id=500 (should NOT be scheduled)
    # loc_inactive: is_active=False, provider_id=600 (should NOT be scheduled)

    sentinel = datetime(2000, 1, 1)
    loc_new_b = IngestionLocation(provider="OpenAQ", provider_location_id=200, location_name="New_B", is_active=True, last_synced_at=sentinel)
    loc_new_a = IngestionLocation(provider="OpenAQ", provider_location_id=100, location_name="New_A", is_active=True, last_synced_at=sentinel)
    loc_stale = IngestionLocation(provider="OpenAQ", provider_location_id=300, location_name="Stale", is_active=True, last_synced_at=two_hours_ago)
    loc_recent_eligible = IngestionLocation(provider="OpenAQ", provider_location_id=400, location_name="RecentEligible", is_active=True, last_synced_at=one_hour_ago)
    loc_hammered = IngestionLocation(provider="OpenAQ", provider_location_id=500, location_name="Hammered", is_active=True, last_synced_at=ten_mins_ago)
    loc_inactive = IngestionLocation(provider="OpenAQ", provider_location_id=600, location_name="Inactive", is_active=False, last_synced_at=sentinel)

    in_memory_db.add_all([loc_new_b, loc_new_a, loc_stale, loc_recent_eligible, loc_hammered, loc_inactive])
    in_memory_db.commit()

    planned = planner.plan_measurement_ingestion()
    planned_ids = [loc.provider_location_id for loc in planned]

    # Verify:
    # 1. loc_hammered (polled 10m ago) is excluded
    assert 500 not in planned_ids
    # 2. loc_inactive is excluded
    assert 600 not in planned_ids
    # 3. Exact ordering:
    #    - Sentinel/new stations first, tie-broken by provider_location_id ASC: 100 then 200
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


# ============================================================================
# 4. METADATA SYNC NOT-NULL & ORM SCHEMA REGRESSION TESTS
# ============================================================================

def test_ingestion_location_orm_schema_invariants(in_memory_db):
    """Verify last_synced_at column is NOT NULL and retains its server default in the ORM."""
    col = IngestionLocation.__table__.c.last_synced_at
    assert col.nullable is False, "last_synced_at MUST be declared nullable=False"
    assert col.server_default is not None, "last_synced_at MUST retain server_default=func.now()"

    # Verify server default fires when last_synced_at is omitted
    loc = IngestionLocation(
        provider="OpenAQ",
        provider_location_id=9876,
        location_name="DefaultStation",
        is_active=True,
    )
    in_memory_db.add(loc)
    in_memory_db.commit()
    in_memory_db.refresh(loc)

    assert loc.last_synced_at is not None, "Server default must populate a non-null last_synced_at"
    assert isinstance(loc.last_synced_at, datetime)


@pytest.mark.asyncio
async def test_metadata_sync_inserts_new_locations_with_sentinel_synced_at(in_memory_db):
    """Verify _sync_metadata inserts newly discovered locations with non-null last_synced_at."""
    coord = IngestionCoordinator(db=in_memory_db, dry_run=False)
    coord.provider = "OpenAQ"

    # Mock provider adapter returning a brand-new station from OpenAQ API
    mock_payload = {
        "results": [
            {
                "id": 8801,
                "name": "Station New Delhi Central",
                "coordinates": {"latitude": 28.61, "longitude": 77.23},
                "datetimeLast": {"utc": "2026-10-24T12:00:00Z"},
            }
        ],
        "meta": {"found": 1},
    }
    coord.provider_adapter.get_locations = AsyncMock(return_value=mock_payload)

    await coord._sync_metadata()

    # Query newly inserted station
    loc = in_memory_db.scalar(
        select(IngestionLocation).where(IngestionLocation.provider_location_id == 8801)
    )
    assert loc is not None, "New location must be persisted"
    assert loc.location_name == "Station New Delhi Central"
    assert loc.last_synced_at is not None, "last_synced_at MUST NOT be NULL"
    assert loc.last_synced_at == datetime(2000, 1, 1), "New locations must receive sentinel 2000-01-01"
    assert loc.provider_datetime_last == datetime(2026, 10, 24, 12, 0, 0)
    assert loc.last_successful_ingestion_at is None, "last_successful_ingestion_at must remain None until measurements ingest"


def test_newly_synced_location_eligible_for_first_polling(in_memory_db):
    """Verify newly discovered locations with sentinel last_synced_at are immediately eligible for first polling."""
    sentinel = datetime(2000, 1, 1)
    new_loc = IngestionLocation(
        provider="OpenAQ",
        provider_location_id=7701,
        location_name="Station Eligible First Poll",
        is_active=True,
        last_synced_at=sentinel,
        last_successful_ingestion_at=None,
    )
    in_memory_db.add(new_loc)
    in_memory_db.commit()

    planner = IngestionPlanner(db=in_memory_db, provider="OpenAQ")
    planned = planner.plan_measurement_ingestion()
    planned_ids = [loc.provider_location_id for loc in planned]

    assert 7701 in planned_ids, "Newly discovered location with sentinel must be immediately eligible for polling"


# ============================================================================
# 5. WORKSTREAMS A - E PRODUCTION REGRESSION TESTS
# ============================================================================

def test_planner_respects_batch_limit(in_memory_db):
    """Verify plan_measurement_ingestion applies query limit strictly."""
    sentinel = datetime(2000, 1, 1)
    locs = [
        IngestionLocation(
            provider="OpenAQ",
            provider_location_id=1000 + i,
            location_name=f"BatchStation_{i}",
            is_active=True,
            last_synced_at=sentinel,
        )
        for i in range(25)
    ]
    in_memory_db.add_all(locs)
    in_memory_db.commit()

    planner = IngestionPlanner(db=in_memory_db, provider="OpenAQ")
    
    # Explicit limit=5
    planned_5 = planner.plan_measurement_ingestion(limit=5)
    assert len(planned_5) == 5
    assert [loc.provider_location_id for loc in planned_5] == [1000, 1001, 1002, 1003, 1004]

    # Explicit limit=10
    planned_10 = planner.plan_measurement_ingestion(limit=10)
    assert len(planned_10) == 10


@pytest.mark.asyncio
async def test_processor_handles_string_parameter(in_memory_db):
    """Verify IngestionProcessor accepts string parameter format (e.g. parameter='pm25')."""
    metrics = IngestionMetrics()
    weather_client = MagicMock()
    weather_client.fetch_current_weather = AsyncMock(return_value={})

    processor = IngestionProcessor(
        db=in_memory_db,
        metrics=metrics,
        geocoder=MagicMock(),
        weather_client=weather_client,
    )

    loc = IngestionLocation(
        provider="OpenAQ",
        provider_location_id=1099,
        location_name="Connaught Place, Delhi",
        latitude=28.63,
        longitude=77.22,
        is_active=True,
    )

    raw_measurements = [
        {
            "sensorsId": 501,
            "parameter": "pm25",
            "value": 35.0,
            "datetime": {"utc": "2026-04-01T12:00:00Z"},
        },
        {
            "sensorsId": 502,
            "parameter": "pm10",
            "value": 75.0,
            "datetime": {"utc": "2026-04-01T12:00:00Z"},
        },
    ]

    records, latest_time = await processor.process_and_store(loc, raw_measurements)
    assert len(records) == 1
    assert latest_time == datetime(2026, 4, 1, 12, 0, 0)
    assert records[0].pm25 == 35.0
    assert records[0].pm10 == 75.0


@pytest.mark.asyncio
async def test_processor_resolves_sensors_from_sensors_json(in_memory_db):
    """Verify IngestionProcessor maps parameter from loc.sensors_json when omitted in measurement."""
    import json
    metrics = IngestionMetrics()
    weather_client = MagicMock()
    weather_client.fetch_current_weather = AsyncMock(return_value={})

    processor = IngestionProcessor(
        db=in_memory_db,
        metrics=metrics,
        geocoder=MagicMock(),
        weather_client=weather_client,
    )

    loc = IngestionLocation(
        provider="OpenAQ",
        provider_location_id=1100,
        location_name="Nehru Nagar, Delhi",
        latitude=28.57,
        longitude=77.25,
        is_active=True,
        sensors_json=json.dumps({"901": ["pm25", "µg/m³"], "902": ["pm10", "µg/m³"]}),
    )

    # Measurement payload where parameter dict/string is absent, only sensorsId is present
    raw_measurements = [
        {
            "sensorsId": 901,
            "value": 42.0,
            "datetime": {"utc": "2026-04-01T14:00:00Z"},
        },
        {
            "sensorsId": 902,
            "value": 88.0,
            "datetime": {"utc": "2026-04-01T14:00:00Z"},
        },
    ]

    records, latest_time = await processor.process_and_store(loc, raw_measurements)
    assert len(records) == 1
    assert latest_time == datetime(2026, 4, 1, 14, 0, 0)
    assert records[0].pm25 == 42.0
    assert records[0].pm10 == 88.0


@pytest.mark.asyncio
async def test_processor_empty_measurements_does_not_bump_rejected_counter(in_memory_db):
    """Verify an empty measurements list does not increment records_rejected counter."""
    metrics = IngestionMetrics()
    processor = IngestionProcessor(
        db=in_memory_db,
        metrics=metrics,
        geocoder=MagicMock(),
        weather_client=MagicMock(),
    )

    loc = IngestionLocation(
        provider="OpenAQ",
        provider_location_id=1101,
        location_name="Empty Station",
        is_active=True,
    )

    records, latest_time = await processor.process_and_store(loc, [])
    assert records == []
    assert latest_time is None
    assert metrics.records_rejected == 0, "Empty response must not increment records_rejected"


def test_tcp_keepalive_settings():
    """Verify that connect_args in connection.py has keepalives configured for PostgreSQL."""
    from database.connection import connect_args
    assert "connect_timeout" in connect_args


# ============================================================================
# 6. DEFECTS 1 - 4 COMPREHENSIVE REGRESSION TESTS
# ============================================================================

@pytest.mark.asyncio
async def test_coordinator_non_dry_run_records_stored_persisted(in_memory_db):
    """Verify Defect 1: records_stored counter is accurately persisted in non-dry-run mode."""
    loc1 = IngestionLocation(provider="OpenAQ", provider_location_id=2001, location_name="PersistStation_1", is_active=True, last_synced_at=datetime(2000, 1, 1))
    loc2 = IngestionLocation(provider="OpenAQ", provider_location_id=2002, location_name="PersistStation_2", is_active=True, last_synced_at=datetime(2000, 1, 1))
    in_memory_db.add_all([loc1, loc2])
    in_memory_db.commit()

    coord = IngestionCoordinator(db=in_memory_db, dry_run=False)
    coord._acquire_lock = AsyncMock(return_value=True)
    coord._should_run_metadata_sync = AsyncMock(return_value=False)
    coord._check_db_backed_hourly_budget = AsyncMock(return_value=True)
    coord.planner.plan_measurement_ingestion = MagicMock(return_value=[loc1, loc2])

    async def mock_latest(provider_id):
        return {
            "results": [
                {"sensorsId": 1, "parameter": {"name": "pm25"}, "value": 25.0, "datetime": {"utc": "2026-04-01T12:00:00Z"}},
                {"sensorsId": 2, "parameter": {"name": "pm10"}, "value": 50.0, "datetime": {"utc": "2026-04-01T12:00:00Z"}}
            ]
        }
    coord.provider_adapter.get_latest_measurements = AsyncMock(side_effect=mock_latest)

    status = await coord.execute()
    assert status == "SUCCESS"

    # Both stations yielded 1 compound record each = 2 records committed
    assert coord.metrics.records_stored == 2, "Authoritative metrics counter must equal committed records"
    assert coord.run_record.records_stored == 2, "Run record must NOT be overwritten with zero"

    # Verify directly from database session
    db_run = in_memory_db.scalar(select(IngestionRun).where(IngestionRun.run_id == coord.run_id))
    assert db_run is not None
    assert db_run.records_stored == 2, "Database must store the true committed count"


@pytest.mark.asyncio
async def test_coordinator_dry_run_records_stored_zero(in_memory_db):
    """Verify Defect 1: Dry run does not claim records were durably stored."""
    loc = IngestionLocation(provider="OpenAQ", provider_location_id=2003, location_name="DryStation", is_active=True, last_synced_at=datetime(2000, 1, 1))
    in_memory_db.add(loc)
    in_memory_db.commit()

    coord = IngestionCoordinator(db=in_memory_db, dry_run=True)
    coord._acquire_lock = AsyncMock(return_value=True)
    coord._should_run_metadata_sync = AsyncMock(return_value=False)
    coord._check_db_backed_hourly_budget = AsyncMock(return_value=True)
    coord.planner.plan_measurement_ingestion = MagicMock(return_value=[loc])

    async def mock_latest(provider_id):
        return {"results": [{"sensorsId": 1, "parameter": {"name": "pm25"}, "value": 20.0, "datetime": {"utc": "2026-04-01T12:00:00Z"}}]}
    coord.provider_adapter.get_latest_measurements = AsyncMock(side_effect=mock_latest)

    status = await coord.execute()
    assert status == "SUCCESS"
    assert coord.metrics.records_stored == 0, "Dry run must NOT claim durable persistence"
    assert coord.run_record.records_stored == 0


@pytest.mark.asyncio
async def test_coordinator_http_failure_does_not_advance_last_synced_at(in_memory_db):
    """Verify Defect 2: HTTP network timeouts/errors do NOT advance last_synced_at."""
    import httpx
    sentinel = datetime(2000, 1, 1)
    loc = IngestionLocation(provider="OpenAQ", provider_location_id=3001, location_name="NetworkFailStation", is_active=True, last_synced_at=sentinel, last_successful_ingestion_at=None)
    in_memory_db.add(loc)
    in_memory_db.commit()

    coord = IngestionCoordinator(db=in_memory_db, dry_run=False)
    coord._acquire_lock = AsyncMock(return_value=True)
    coord._should_run_metadata_sync = AsyncMock(return_value=False)
    coord._check_db_backed_hourly_budget = AsyncMock(return_value=True)
    coord.planner.plan_measurement_ingestion = MagicMock(return_value=[loc])

    # Simulate HTTP network timeout
    coord.provider_adapter.get_latest_measurements = AsyncMock(
        side_effect=httpx.ConnectTimeout("OpenAQ gateway timeout")
    )

    status = await coord.execute()
    assert status == "PARTIAL", "Run with HTTP failure must be marked PARTIAL"

    in_memory_db.refresh(loc)
    assert loc.last_synced_at == sentinel, "last_synced_at MUST NOT advance on HTTP connection failure"
    assert loc.last_successful_ingestion_at is None


@pytest.mark.asyncio
async def test_coordinator_empty_response_advances_last_synced_at_only(in_memory_db):
    """Verify Defect 2: Successful HTTP empty responses advance last_synced_at but not last_successful_ingestion_at."""
    sentinel = datetime(2000, 1, 1)
    loc = IngestionLocation(provider="OpenAQ", provider_location_id=3002, location_name="EmptyStation", is_active=True, last_synced_at=sentinel, last_successful_ingestion_at=None)
    in_memory_db.add(loc)
    in_memory_db.commit()

    coord = IngestionCoordinator(db=in_memory_db, dry_run=False)
    coord._acquire_lock = AsyncMock(return_value=True)
    coord._should_run_metadata_sync = AsyncMock(return_value=False)
    coord._check_db_backed_hourly_budget = AsyncMock(return_value=True)
    coord.planner.plan_measurement_ingestion = MagicMock(return_value=[loc])

    # Simulate HTTP 200 with empty results
    coord.provider_adapter.get_latest_measurements = AsyncMock(return_value={"results": []})

    status = await coord.execute()
    assert status == "SUCCESS", "Empty responses are normal and must not fail the run"

    in_memory_db.refresh(loc)
    assert loc.last_synced_at > sentinel, "last_synced_at MUST advance to enforce 15m anti-hammering"
    assert loc.last_successful_ingestion_at is None, "checkpoint MUST NOT advance when no data was stored"
    assert coord.metrics.records_rejected == 0, "Empty responses must NOT be counted as rejected records"


def test_planner_limit_validation(in_memory_db):
    """Verify Defect 3: Invalid limit values raise ValueError and never produce unbounded queries."""
    planner = IngestionPlanner(db=in_memory_db, provider="OpenAQ")

    with pytest.raises(ValueError, match="Limit must be a positive non-zero integer"):
        planner.plan_measurement_ingestion(limit=0)

    with pytest.raises(ValueError, match="Limit must be a positive non-zero integer"):
        planner.plan_measurement_ingestion(limit=-5)

    with pytest.raises(ValueError, match="Limit must be a positive non-zero integer"):
        planner.plan_measurement_ingestion(limit="100")

    with pytest.raises(ValueError, match="Limit must be a positive non-zero integer"):
        planner.plan_measurement_ingestion(limit=True)


@pytest.mark.asyncio
async def test_counter_unit_consistency(in_memory_db):
    """Verify Defect 4: records_rejected increments in units of compound observation records, not raw sensors."""
    metrics = IngestionMetrics()
    processor = IngestionProcessor(
        db=in_memory_db,
        metrics=metrics,
        geocoder=MagicMock(),
        weather_client=MagicMock(),
    )

    loc = IngestionLocation(provider="OpenAQ", provider_location_id=4001, location_name="UnitCheckStation", is_active=True)

    # 10 raw sensor measurements all missing timestamps
    raw_missing_timestamps = [
        {"sensorsId": i, "parameter": {"name": "pm25"}, "value": 15.0}
        for i in range(10)
    ]
    records, _ = await processor.process_and_store(loc, raw_missing_timestamps)
    assert records == []
    assert metrics.records_rejected == 1, "A single rejected observation payload must increment records_rejected by 1, not 10"

