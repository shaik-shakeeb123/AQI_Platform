"""Offline unit and regression tests for ingestion remediation.

Covers:
1. OpenAQ v3 timestamp handling (various formats, missing/malformed formats).
2. Location scheduling fairness (nulls first, stalest next, deterministic tie-breakers, 15m rule).
3. Metric consistency (locations_skipped invariant, record counter units).
4. Safe isolated database fixtures (zero production DB writes).
"""

from __future__ import annotations

import asyncio
import json
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
    assert status in ("SUCCESS", "DRY_RUN")
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



# ---------------------------------------------------------------------------
# Section 5 & 6 Production-Readiness Remediation Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_metadata_sync_triggered_when_active_stations_lack_sensors_json(in_memory_db):
    """Verify _should_run_metadata_sync schedules sync when active stations lack sensor mappings, even if recent."""
    now = datetime.now()
    # Add active locations without sensor metadata, updated recently (< 6 hours ago)
    for i in range(15):
        in_memory_db.add(
            IngestionLocation(
                provider="OpenAQ",
                provider_location_id=5000 + i,
                location_name=f"Station_{i}",
                is_active=True,
                sensors_json=None,
                updated_at=now - timedelta(minutes=30),
            )
        )
    in_memory_db.commit()

    coord = IngestionCoordinator(db=in_memory_db, dry_run=True)
    should_sync = await coord._should_run_metadata_sync()
    assert should_sync is True, "Metadata sync must be scheduled when >10 active stations lack sensors_json"


def test_sensor_map_helpers_and_key_normalization():
    """Verify sensor map parsing, string/integer normalization, and merging rules."""
    from data_sync.data_processor import (
        parse_and_validate_sensors_json, merge_sensor_maps, lookup_sensor_mapping
    )

    # 1. Normalization and malformed inputs
    assert parse_and_validate_sensors_json(None) == {}
    assert parse_and_validate_sensors_json("") == {}
    assert parse_and_validate_sensors_json("{malformed json") == {}
    assert parse_and_validate_sensors_json("[]") == {}
    assert parse_and_validate_sensors_json("123") == {}

    # 2. String keys with mixed int/string lookups
    valid_json = json.dumps({"101": ["PM25", "µg/m³"], "102": ["PM10", "µg/m³"]})
    parsed = parse_and_validate_sensors_json(valid_json)
    assert parsed["101"] == ("pm25", "µg/m³")
    assert parsed["102"] == ("pm10", "µg/m³")

    # lookup_sensor_mapping supports string key, int key, and digit normalization
    assert lookup_sensor_mapping(parsed, 101) == ("pm25", "µg/m³")
    assert lookup_sensor_mapping(parsed, "101") == ("pm25", "µg/m³")
    assert lookup_sensor_mapping(parsed, 999) is None

    # 3. Safe merge does not overwrite valid data with empty/invalid data
    existing = {"101": ("pm25", "µg/m³"), "102": ("pm10", "")}
    incoming = {"102": ("pm10", "µg/m³"), "103": ("no2", "ppb"), "101": ("", "")}
    merged = merge_sensor_maps(existing, incoming)
    assert merged["101"] == ("pm25", "µg/m³"), "Valid existing data must not be overwritten by empty data"
    assert merged["102"] == ("pm10", "µg/m³"), "Missing unit should be enhanced if available"
    assert merged["103"] == ("no2", "ppb"), "New sensor should be added"


@pytest.mark.asyncio
async def test_geocoding_timeout_falls_back_to_unknown_and_preserves_records(in_memory_db):
    """Verify Nominatim timeout does not crash the worker or discard valid pollutant observations."""
    import httpx
    metrics = IngestionMetrics()
    geocoder = MagicMock()
    # Simulate Nominatim timeout
    geocoder.reverse_geocode_city = AsyncMock(side_effect=httpx.ConnectTimeout("Nominatim timed out"))

    weather_client = MagicMock()
    weather_client.fetch_current_weather = AsyncMock(return_value={})

    processor = IngestionProcessor(
        db=in_memory_db,
        metrics=metrics,
        geocoder=geocoder,
        weather_client=weather_client,
    )

    # Station name that local regex parser cannot resolve, forcing reverse geocoding
    loc = IngestionLocation(
        provider="OpenAQ",
        provider_location_id=5500,
        location_name="Continuous Ambient Air Quality Monitoring Station 7",
        latitude=28.50,
        longitude=77.20,
        is_active=True,
    )

    raw_measurements = [
        {
            "sensorsId": 701,
            "parameter": "pm25",
            "value": 45.0,
            "datetime": {"utc": "2026-04-01T15:00:00Z"},
        }
    ]

    records, latest_time = await processor.process_and_store(loc, raw_measurements)
    assert len(records) == 1, "Record must be created despite geocoding timeout"
    assert records[0].city == "Unknown", "Fallback city must be Unknown"
    assert records[0].pm25 == 45.0
    assert latest_time == datetime(2026, 4, 1, 15, 0, 0)


@pytest.mark.asyncio
async def test_targeted_sensor_repair_on_missing_sensors_json(in_memory_db):
    """Verify repair_location_sensor_metadata queries OpenAQ and populates sensors_json."""
    loc = IngestionLocation(
        provider="OpenAQ",
        provider_location_id=5600,
        location_name="Station_Targeted_Repair",
        is_active=True,
        sensors_json=None,
    )
    in_memory_db.add(loc)
    in_memory_db.commit()

    coord = IngestionCoordinator(db=in_memory_db, dry_run=True)
    # Mock single location metadata response
    coord.provider_adapter.get_location = AsyncMock(return_value={
        "results": [{
            "id": 5600,
            "sensors": [
                {"id": 801, "parameter": {"name": "pm25", "units": "µg/m³"}},
                {"id": 802, "parameter": {"name": "pm10", "units": "µg/m³"}}
            ]
        }]
    })

    success = await coord.repair_location_sensor_metadata(loc)
    assert success is True
    assert loc.sensors_json is not None
    sensors = json.loads(loc.sensors_json)
    assert "801" in sensors
    assert sensors["801"] == ["pm25", "µg/m³"]


@pytest.mark.asyncio
async def test_processor_learns_sensors_from_raw_measurements_inline(in_memory_db):
    """Verify processor learns and caches sensor definitions from raw measurements if initially missing."""
    metrics = IngestionMetrics()
    processor = IngestionProcessor(
        db=in_memory_db,
        metrics=metrics,
        geocoder=MagicMock(),
        weather_client=MagicMock(),
    )

    loc = IngestionLocation(
        provider="OpenAQ",
        provider_location_id=5700,
        location_name="Connaught Place, Delhi",
        latitude=28.63,
        longitude=77.22,
        is_active=True,
        sensors_json=None,  # No cached metadata
    )

    raw_measurements = [
        {
            "sensorsId": 991,
            "parameter": {"name": "pm25", "units": "µg/m³"},
            "value": 30.0,
            "datetime": {"utc": "2026-04-01T16:00:00Z"},
        }
    ]

    records, _ = await processor.process_and_store(loc, raw_measurements)
    assert len(records) == 1
    assert loc.sensors_json is not None, "Processor must cache learned sensors_json on loc"
    cached = json.loads(loc.sensors_json)
    assert "991" in cached
    assert cached["991"] == ["pm25", "µg/m³"]


def test_location_outcome_counters_in_metrics():
    """Verify IngestionMetrics tracks location outcomes and summarizes them clearly."""
    m = IngestionMetrics()
    m.locations_examined = 100
    m.locations_attempted = 100
    m.locations_successful = 90
    m.locations_empty = 5
    m.locations_processing_errors = 3
    m.locations_http_errors = 2

    summary = m.summarize()
    assert "ok=90" in summary
    assert "empty=5" in summary
    assert "proc_err=3" in summary
    assert "http_err=2" in summary


# ============================================================================
# CORRECTIONS A, B, C: CLI BOUNDS, METADATA REFRESH SAFETY & OBSERVABILITY
# ============================================================================

def test_run_once_cli_argument_parsing_and_validation():
    """Verify data_sync.run_once.parse_args parses flags and rejects invalid/unknown options."""
    from data_sync.run_once import parse_args

    # Default invocation (no args)
    args = parse_args([])
    assert args.dry_run is False
    assert args.limit is None

    # --dry-run flag
    args = parse_args(["--dry-run"])
    assert args.dry_run is True
    assert args.limit is None

    # --batch-size and --limit alias
    args = parse_args(["--batch-size", "5"])
    assert args.limit == 5

    args = parse_args(["--limit", "10"])
    assert args.limit == 10

    # Combined flags
    args = parse_args(["--dry-run", "--batch-size", "3"])
    assert args.dry_run is True
    assert args.limit == 3

    # Invalid limits: must fail with SystemExit(2)
    with pytest.raises(SystemExit):
        parse_args(["--batch-size", "-1"])

    with pytest.raises(SystemExit):
        parse_args(["--batch-size", "0"])

    with pytest.raises(SystemExit):
        parse_args(["--batch-size", "abc"])

    # Unknown flags: must fail with SystemExit(2)
    with pytest.raises(SystemExit):
        parse_args(["--unknown-flag"])


@pytest.mark.asyncio
async def test_run_once_status_to_exit_code_and_propagation():
    """Verify data_sync.run_once.main maps statuses to observable exit codes and passes arguments."""
    from data_sync.run_once import main

    # 1. Argument propagation into run_ingestion_job
    with patch("data_sync.run_once.run_ingestion_job", new_callable=AsyncMock) as mock_job:
        mock_job.return_value = "SUCCESS"
        code = await main(["--dry-run", "--batch-size", "5"])
        assert code == 0
        mock_job.assert_awaited_once_with(dry_run=True, limit=5)

    # 2. SUCCESS status -> 0
    with patch("data_sync.run_once.run_ingestion_job", new_callable=AsyncMock) as mock_job:
        mock_job.return_value = "SUCCESS"
        assert await main([]) == 0

    # 3. SKIPPED status -> 0
    with patch("data_sync.run_once.run_ingestion_job", new_callable=AsyncMock) as mock_job:
        mock_job.return_value = "SKIPPED_LOCKED"
        assert await main([]) == 0

    # 4. PARTIAL status -> 2 (Observable failure for CI/CD, not silent exit 0)
    with patch("data_sync.run_once.run_ingestion_job", new_callable=AsyncMock) as mock_job:
        mock_job.return_value = "PARTIAL"
        assert await main([]) == 2

    # 5. FAILED status -> 1
    with patch("data_sync.run_once.run_ingestion_job", new_callable=AsyncMock) as mock_job:
        mock_job.return_value = "FAILED"
        assert await main([]) == 1

    # 6. Invalid CLI limits fail cleanly with exit code 2 before running the job
    with patch("data_sync.run_once.run_ingestion_job", new_callable=AsyncMock) as mock_job:
        code = await main(["--batch-size", "-5"])
        assert code == 2
        mock_job.assert_not_called()


def test_coordinator_batch_limit_validation_and_propagation(in_memory_db):
    """Verify IngestionCoordinator validates batch_limit and planner limits SQL queries."""
    # Invalid limit checks
    with pytest.raises(ValueError):
        IngestionCoordinator(db=in_memory_db, batch_limit=0)

    with pytest.raises(ValueError):
        IngestionCoordinator(db=in_memory_db, batch_limit=-10)

    with pytest.raises(ValueError):
        IngestionCoordinator(db=in_memory_db, batch_limit="5")  # type: ignore

    # Valid limit propagates into planner
    for i in range(10):
        in_memory_db.add(
            IngestionLocation(
                provider="OpenAQ",
                provider_location_id=7000 + i,
                location_name=f"Station_{i}",
                is_active=True,
                sensors_json="{}",
                last_synced_at=datetime(2000, 1, 1),
            )
        )
    in_memory_db.commit()

    coord = IngestionCoordinator(db=in_memory_db, dry_run=True, batch_limit=3)
    planned = coord.planner.plan_measurement_ingestion(limit=coord.batch_limit)
    assert len(planned) == 3, "Batch limit must be strictly enforced at query level"


@pytest.mark.asyncio
async def test_confirmed_empty_sensors_json_does_not_trigger_full_catalog_sync(in_memory_db):
    """Verify _should_run_metadata_sync does NOT trigger when stations have confirmed empty metadata ('{}')."""
    now = datetime.now()
    # Add active stations where metadata was checked and confirmed empty ("{}")
    for i in range(5):
        in_memory_db.add(
            IngestionLocation(
                provider="OpenAQ",
                provider_location_id=7100 + i,
                location_name=f"EmptyStation_{i}",
                is_active=True,
                sensors_json="{}",  # Confirmed empty upstream
                updated_at=now - timedelta(minutes=45),
            )
        )
    in_memory_db.commit()

    coord = IngestionCoordinator(db=in_memory_db, dry_run=True)
    should_sync = await coord._should_run_metadata_sync()
    assert should_sync is False, "Confirmed empty stations ('{}') must not trigger repeated catalog downloads"

    # Now add a truly uninitialized station (sensors_json=None)
    uninitialized = IngestionLocation(
        provider="OpenAQ",
        provider_location_id=7200,
        location_name="UninitializedStation",
        is_active=True,
        sensors_json=None,
        updated_at=now - timedelta(minutes=45),
    )
    in_memory_db.add(uninitialized)
    in_memory_db.commit()

    should_sync_now = await coord._should_run_metadata_sync()
    assert should_sync_now is True, "Truly uninitialized station (None) must trigger metadata sync"


@pytest.mark.asyncio
async def test_targeted_sensor_repair_marks_empty_upstream_as_confirmed_empty(in_memory_db):
    """Verify repair_location_sensor_metadata sets sensors_json='{}' if OpenAQ returns no sensors."""
    loc = IngestionLocation(
        provider="OpenAQ",
        provider_location_id=7300,
        location_name="Station_No_Sensors_Upstream",
        is_active=True,
        sensors_json=None,
    )
    in_memory_db.add(loc)
    in_memory_db.commit()

    coord = IngestionCoordinator(db=in_memory_db, dry_run=True)
    # OpenAQ returns location with empty sensors list
    coord.provider_adapter.get_location = AsyncMock(return_value={
        "results": [{
            "id": 7300,
            "sensors": []
        }]
    })

    success = await coord.repair_location_sensor_metadata(loc)
    assert success is False
    assert loc.sensors_json == "{}", "Station must be marked with confirmed empty JSON ('{}')"


# ============================================================================
# TEMPORAL WEATHER ENRICHMENT SAFETY REGRESSION TESTS (RUN 23 FIX)
# ============================================================================

@pytest.mark.asyncio
async def test_historical_observation_skips_current_weather_enrichment(in_memory_db):
    """Verify historical observation (e.g. 2022 Run 23) does NOT call current weather or receive live weather."""
    metrics = IngestionMetrics()
    weather_client = MagicMock()
    weather_client.fetch_current_weather = AsyncMock(return_value={
        "current": {
            "wind_speed_10m": 99.9,
            "wind_direction_10m": 350.0,
            "surface_pressure": 999.0,
            "precipitation": 50.0,
        }
    })

    processor = IngestionProcessor(
        db=in_memory_db,
        metrics=metrics,
        geocoder=MagicMock(),
        weather_client=weather_client,
    )

    loc = IngestionLocation(
        provider="OpenAQ",
        provider_location_id=2301,
        location_name="Shadipur, Delhi - CPCB",
        latitude=28.65,
        longitude=77.16,
        is_active=True,
        sensors_json=json.dumps({"1": ["pm25", "µg/m³"], "2": ["pm10", "µg/m³"]}),
    )

    # Historical observation from Run 23: 2022-10-31 02:00:00
    raw_measurements = [
        {
            "sensorsId": 1,
            "value": 139.2,
            "datetime": {"utc": "2022-10-31T02:00:00Z"},
        },
        {
            "sensorsId": 2,
            "value": 833.9,
            "datetime": {"utc": "2022-10-31T02:00:00Z"},
        },
    ]

    records, latest_time = await processor.process_and_store(loc, raw_measurements)

    # 1. External weather call must be completely skipped
    weather_client.fetch_current_weather.assert_not_called()
    assert metrics.openmeteo_requests == 0, "No external Open-Meteo requests for historical data"

    # 2. Record must be preserved and validated
    assert len(records) == 1
    assert latest_time == datetime(2022, 10, 31, 2, 0, 0)
    rec = records[0]
    assert rec.pm25 == 139.2
    assert rec.pm10 == 833.9
    assert rec.aqi == 500.0  # CPCB/EPA capped at 500

    # 3. Weather fields must be omitted (None), NOT contaminated with live 99.9 weather
    assert rec.wind_speed is None
    assert rec.wind_direction is None
    assert rec.precipitation is None
    assert rec.pressure is None


@pytest.mark.asyncio
async def test_contemporaneous_observation_retains_current_weather_enrichment(in_memory_db):
    """Verify contemporaneous observation (e.g. 20 min ago) DOES fetch and merge current weather."""
    metrics = IngestionMetrics()
    weather_client = MagicMock()
    weather_client.fetch_current_weather = AsyncMock(return_value={
        "current": {
            "wind_speed_10m": 12.5,
            "wind_direction_10m": 180.0,
            "surface_pressure": 1013.2,
            "precipitation": 0.0,
            "temperature_2m": 26.5,
            "relative_humidity_2m": 58.0,
        }
    })

    processor = IngestionProcessor(
        db=in_memory_db,
        metrics=metrics,
        geocoder=MagicMock(),
        weather_client=weather_client,
    )

    loc = IngestionLocation(
        provider="OpenAQ",
        provider_location_id=2302,
        location_name="Live Station, Delhi",
        latitude=28.60,
        longitude=77.20,
        is_active=True,
        sensors_json=json.dumps({"10": ["pm25", "µg/m³"]}),
    )

    # Contemporaneous timestamp (20 minutes ago UTC)
    recent_time = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=20)
    raw_measurements = [
        {
            "sensorsId": 10,
            "value": 45.0,
            "datetime": {"utc": recent_time.isoformat() + "Z"},
        }
    ]

    records, _ = await processor.process_and_store(loc, raw_measurements)

    # 1. Weather client must be called
    weather_client.fetch_current_weather.assert_awaited_once_with(28.60, 77.20)
    assert metrics.openmeteo_requests == 1

    # 2. Weather fields must be populated
    assert len(records) == 1
    rec = records[0]
    assert rec.pm25 == 45.0
    assert rec.wind_speed == 12.5
    assert rec.wind_direction == 180.0
    assert rec.pressure == 1013.2
    assert rec.precipitation == 0.0
    assert rec.temperature == 26.5
    assert rec.humidity == 58.0


@pytest.mark.asyncio
async def test_failed_or_skipped_weather_request_preserves_valid_pollutants(in_memory_db):
    """Verify Open-Meteo failure does not drop the record or fail the worker."""
    import httpx
    metrics = IngestionMetrics()
    weather_client = MagicMock()
    # Simulate network timeout connecting to Open-Meteo
    weather_client.fetch_current_weather = AsyncMock(side_effect=httpx.ConnectTimeout("Open-Meteo timed out"))

    processor = IngestionProcessor(
        db=in_memory_db,
        metrics=metrics,
        geocoder=MagicMock(),
        weather_client=weather_client,
    )

    loc = IngestionLocation(
        provider="OpenAQ",
        provider_location_id=2303,
        location_name="Station_Weather_Failure",
        latitude=28.70,
        longitude=77.10,
        is_active=True,
        sensors_json=json.dumps({"20": ["pm25", "µg/m³"]}),
    )

    recent_time = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=10)
    raw_measurements = [
        {
            "sensorsId": 20,
            "value": 35.0,
            "datetime": {"utc": recent_time.isoformat() + "Z"},
        }
    ]

    records, _ = await processor.process_and_store(loc, raw_measurements)

    # Record must be stored successfully despite weather failure
    assert len(records) == 1
    assert records[0].pm25 == 35.0
    assert records[0].wind_speed is None
    assert records[0].aqi is not None
    assert metrics.records_rejected == 0


def test_is_contemporaneous_helper_boundaries_and_mismatched_times():
    """Verify is_contemporaneous boundary checks, clock drift tolerance, and non-contemporaneous rejection."""
    from data_sync.data_processor import is_contemporaneous

    now = datetime(2026, 10, 25, 12, 0, 0)

    # 1. Historical observation from 2022 (Run 23)
    assert is_contemporaneous(datetime(2022, 10, 31, 2, 0, 0), reference_time=now) is False

    # 2. 1 day ago
    assert is_contemporaneous(now - timedelta(days=1), reference_time=now) is False

    # 3. 3 hours ago (beyond default 2-hour tolerance)
    assert is_contemporaneous(now - timedelta(hours=3), reference_time=now) is False

    # 4. Exactly 2 hours ago (boundary)
    assert is_contemporaneous(now - timedelta(hours=2), reference_time=now) is True

    # 5. 30 minutes ago (typical contemporaneous run)
    assert is_contemporaneous(now - timedelta(minutes=30), reference_time=now) is True

    # 6. Small clock drift (5 minutes in future)
    assert is_contemporaneous(now + timedelta(minutes=5), reference_time=now) is True

    # 7. Unreasonable future timestamp (30 minutes in future)
    assert is_contemporaneous(now + timedelta(minutes=30), reference_time=now) is False

    # 8. Malformed or None timestamps
    assert is_contemporaneous(None, reference_time=now) is False
    assert is_contemporaneous("not a datetime", reference_time=now) is False  # type: ignore


@pytest.mark.asyncio
async def test_existing_pollutant_processing_and_aqi_calculation_remain_unchanged(in_memory_db):
    """Verify exact Run 23 pollutant and AQI values are reproduced and OpenAQ inline temperature/humidity is preserved."""
    metrics = IngestionMetrics()
    processor = IngestionProcessor(
        db=in_memory_db,
        metrics=metrics,
        geocoder=MagicMock(),
        weather_client=MagicMock(),
    )

    # 1. Shadipur Delhi (Run 23): PM2.5 139.2, PM10 833.9 -> AQI 500
    loc1 = IngestionLocation(
        provider="OpenAQ", provider_location_id=2304, location_name="Shadipur, Delhi - CPCB",
        is_active=True, sensors_json=json.dumps({"1": ["pm25", "µg/m³"], "2": ["pm10", "µg/m³"]})
    )
    raw1 = [
        {"sensorsId": 1, "value": 139.2, "datetime": {"utc": "2022-10-31T02:00:00Z"}},
        {"sensorsId": 2, "value": 833.9, "datetime": {"utc": "2022-10-31T02:00:00Z"}},
    ]
    records1, _ = await processor.process_and_store(loc1, raw1)
    assert len(records1) == 1
    assert records1[0].pm25 == 139.2
    assert records1[0].pm10 == 833.9
    assert records1[0].aqi == 500.0
    assert records1[0].dominant_pollutant == "PM10"

    # 2. Maninagar Ahmedabad (Run 23): PM2.5 43.94, PM10 0 -> AQI 121.68
    loc2 = IngestionLocation(
        provider="OpenAQ", provider_location_id=2305, location_name="Maninagar, Ahmedabad - GPCB",
        is_active=True, sensors_json=json.dumps({"3": ["pm25", "µg/m³"], "4": ["pm10", "µg/m³"], "5": ["temperature", "c"], "6": ["humidity", "%"]})
    )
    raw2 = [
        {"sensorsId": 3, "value": 43.94, "datetime": {"utc": "2022-10-31T01:45:00Z"}},
        {"sensorsId": 4, "value": 0.0, "datetime": {"utc": "2022-10-31T01:45:00Z"}},
        {"sensorsId": 5, "value": 28.5, "datetime": {"utc": "2022-10-31T01:45:00Z"}},
        {"sensorsId": 6, "value": 55.0, "datetime": {"utc": "2022-10-31T01:45:00Z"}},
    ]
    records2, _ = await processor.process_and_store(loc2, raw2)
    assert len(records2) == 1
    assert records2[0].pm25 == 43.94
    assert records2[0].pm10 == 0.0
    assert records2[0].aqi == 121.68
    assert records2[0].dominant_pollutant == "PM2.5"
    # Inline OpenAQ temperature and humidity must be preserved!
    assert records2[0].temperature == 28.5
    assert records2[0].humidity == 55.0
    # External weather fields must be None
    assert records2[0].wind_speed is None
    assert records2[0].pressure is None


# ============================================================================
# DRY-RUN ORPHAN CLEANUP & AUDIT PERSISTENCE REGRESSION TESTS
# ============================================================================

@pytest.mark.asyncio
async def test_dry_run_measurement_writes_rolled_back(in_memory_db):
    """Regression Test 1: Verify dry-run measurement writes to aqi_data are completely rolled back."""
    from database.models.aqi_data import AQIData

    loc = IngestionLocation(
        provider="OpenAQ", provider_location_id=8101, location_name="RollbackTestStation",
        is_active=True, last_synced_at=datetime(2000, 1, 1),
        sensors_json=json.dumps({"1": ["pm25", "µg/m³"], "2": ["pm10", "µg/m³"]})
    )
    in_memory_db.add(loc)
    in_memory_db.commit()

    coord = IngestionCoordinator(db=in_memory_db, dry_run=True)
    coord._acquire_lock = AsyncMock(return_value=True)
    coord._should_run_metadata_sync = AsyncMock(return_value=False)
    coord._check_db_backed_hourly_budget = AsyncMock(return_value=True)
    coord.planner.plan_measurement_ingestion = MagicMock(return_value=[loc])

    async def mock_latest(provider_id):
        return {
            "results": [
                {"sensorsId": 1, "value": 35.0, "datetime": {"utc": "2026-04-01T12:00:00Z"}},
                {"sensorsId": 2, "value": 70.0, "datetime": {"utc": "2026-04-01T12:00:00Z"}},
            ]
        }
    coord.provider_adapter.get_latest_measurements = AsyncMock(side_effect=mock_latest)

    status = await coord.execute()
    assert status in ("SUCCESS", "DRY_RUN")

    # Confirm ZERO rows persist in aqi_data
    records = in_memory_db.scalars(select(AQIData).where(AQIData.location_name == "RollbackTestStation")).all()
    assert len(records) == 0, "Staged measurement records must be completely rolled back in dry-run mode"


@pytest.mark.asyncio
async def test_dry_run_location_and_watermark_changes_rolled_back(in_memory_db):
    """Regression Test 2: Verify dry-run location last_synced_at and watermark advances are rolled back."""
    from data_sync.ingestion.models import IngestionState

    sentinel_time = datetime(2020, 1, 1, 12, 0, 0)
    loc = IngestionLocation(
        provider="OpenAQ", provider_location_id=8102, location_name="WatermarkStation",
        is_active=True, last_synced_at=sentinel_time, last_successful_ingestion_at=None,
        sensors_json=json.dumps({"1": ["pm25", "µg/m³"]})
    )
    state = IngestionState(
        provider="OpenAQ", resource="measurements", scope="all",
        watermark=sentinel_time, status="SUCCESS"
    )
    in_memory_db.add_all([loc, state])
    in_memory_db.commit()

    coord = IngestionCoordinator(db=in_memory_db, dry_run=True)
    coord._acquire_lock = AsyncMock(return_value=True)
    coord._should_run_metadata_sync = AsyncMock(return_value=False)
    coord._check_db_backed_hourly_budget = AsyncMock(return_value=True)
    coord.planner.plan_measurement_ingestion = MagicMock(return_value=[loc])

    async def mock_latest(provider_id):
        return {
            "results": [
                {"sensorsId": 1, "value": 25.0, "datetime": {"utc": "2026-04-01T12:00:00Z"}}
            ]
        }
    coord.provider_adapter.get_latest_measurements = AsyncMock(side_effect=mock_latest)

    status = await coord.execute()
    assert status in ("SUCCESS", "DRY_RUN")

    in_memory_db.refresh(loc)
    in_memory_db.refresh(state)

    assert loc.last_synced_at == sentinel_time, "Location last_synced_at must NOT advance in dry-run mode"
    assert loc.last_successful_ingestion_at is None, "Location last_successful_ingestion_at must NOT advance in dry-run mode"
    assert state.watermark == sentinel_time, "Global watermark state must NOT advance in dry-run mode"


@pytest.mark.asyncio
async def test_dry_run_orphan_cleanup_is_skipped(in_memory_db):
    """Regression Test 3: Verify orphaned-run cleanup is bypassed in dry-run mode (no CRASHED updates)."""
    old_run = IngestionRun(
        run_id="historical_running_orphan_1",
        provider="OpenAQ",
        mode="SCHEDULED",
        status="RUNNING",
        started_at=datetime(2026, 1, 1, 0, 0, 0),
        finished_at=None,
    )
    in_memory_db.add(old_run)
    in_memory_db.commit()

    coord = IngestionCoordinator(db=in_memory_db, dry_run=True)
    coord._acquire_lock = AsyncMock(return_value=True)
    coord._should_run_metadata_sync = AsyncMock(return_value=False)
    coord._check_db_backed_hourly_budget = AsyncMock(return_value=True)
    coord.planner.plan_measurement_ingestion = MagicMock(return_value=[])

    status = await coord.execute()
    assert status in ("SUCCESS", "DRY_RUN")

    in_memory_db.refresh(old_run)
    assert old_run.status == "RUNNING", "Historical RUNNING run must NOT be mutated to CRASHED during dry-run"
    assert old_run.finished_at is None


@pytest.mark.asyncio
async def test_normal_run_performs_orphan_cleanup(in_memory_db):
    """Regression Test 4: Verify normal ingestion runs still perform orphan recovery as intended."""
    old_run = IngestionRun(
        run_id="historical_running_orphan_2",
        provider="OpenAQ",
        mode="SCHEDULED",
        status="RUNNING",
        started_at=datetime(2026, 1, 1, 0, 0, 0),
        finished_at=None,
    )
    in_memory_db.add(old_run)
    in_memory_db.commit()

    coord = IngestionCoordinator(db=in_memory_db, dry_run=False)
    coord._acquire_lock = AsyncMock(return_value=True)
    coord._should_run_metadata_sync = AsyncMock(return_value=False)
    coord._check_db_backed_hourly_budget = AsyncMock(return_value=True)
    coord.planner.plan_measurement_ingestion = MagicMock(return_value=[])

    status = await coord.execute()
    assert status == "SUCCESS"

    in_memory_db.refresh(old_run)
    assert old_run.status == "CRASHED", "Normal ingestion must update orphaned RUNNING rows to CRASHED"
    assert old_run.error_message == "Process terminated unexpectedly (orphaned RUNNING status)"
    assert old_run.finished_at is not None


@pytest.mark.asyncio
async def test_dry_run_audit_summary_persists_independently(in_memory_db):
    """Regression Test 5: Verify dry-run audit summary persists with DRY_RUN status and zero records_stored."""
    from database.models.aqi_data import AQIData

    loc = IngestionLocation(
        provider="OpenAQ", provider_location_id=8105, location_name="AuditPersistStation",
        is_active=True, last_synced_at=datetime(2000, 1, 1),
        sensors_json=json.dumps({"1": ["pm25", "µg/m³"]})
    )
    in_memory_db.add(loc)
    in_memory_db.commit()

    coord = IngestionCoordinator(db=in_memory_db, dry_run=True)
    coord._acquire_lock = AsyncMock(return_value=True)
    coord._should_run_metadata_sync = AsyncMock(return_value=False)
    coord._check_db_backed_hourly_budget = AsyncMock(return_value=True)
    coord.planner.plan_measurement_ingestion = MagicMock(return_value=[loc])

    async def mock_latest(provider_id):
        return {
            "results": [
                {"sensorsId": 1, "value": 45.0, "datetime": {"utc": "2026-04-01T12:00:00Z"}},
                {"sensorsId": 1, "value": 48.0, "datetime": {"utc": "2026-04-01T13:00:00Z"}},
            ]
        }
    coord.provider_adapter.get_latest_measurements = AsyncMock(side_effect=mock_latest)

    status = await coord.execute()
    assert status in ("SUCCESS", "DRY_RUN")

    # Query the persisted IngestionRun record
    db_run = in_memory_db.scalar(select(IngestionRun).where(IngestionRun.run_id == coord.run_id))
    assert db_run is not None, "Dry run audit summary must be persisted in ingestion_runs"
    assert db_run.status == "DRY_RUN", "Status in ingestion_runs must be DRY_RUN"
    assert db_run.dry_run is True, "dry_run flag must be True"
    assert db_run.records_stored == 0, "records_stored must remain strictly 0 in dry-run"
    assert db_run.records_fetched == 2
    assert db_run.locations_examined == 1
    assert db_run.locations_attempted == 1
    assert db_run.execution_seconds is not None and db_run.execution_seconds >= 0

    # Verify measurement records were not persisted
    records = in_memory_db.scalars(select(AQIData).where(AQIData.location_name == "AuditPersistStation")).all()
    assert len(records) == 0, "Zero aqi_data rows must exist in database"


@pytest.mark.asyncio
async def test_audit_persistence_failure_cannot_commit_staged_data(in_memory_db):
    """Regression Test 6: Verify a failure during audit persistence cannot commit staged measurement data."""
    from database.models.aqi_data import AQIData

    loc = IngestionLocation(
        provider="OpenAQ", provider_location_id=8106, location_name="AuditFailStation",
        is_active=True, last_synced_at=datetime(2000, 1, 1),
        sensors_json=json.dumps({"1": ["pm25", "µg/m³"]})
    )
    in_memory_db.add(loc)
    in_memory_db.commit()

    coord = IngestionCoordinator(db=in_memory_db, dry_run=True)
    coord._acquire_lock = AsyncMock(return_value=True)
    coord._should_run_metadata_sync = AsyncMock(return_value=False)
    coord._check_db_backed_hourly_budget = AsyncMock(return_value=True)
    coord.planner.plan_measurement_ingestion = MagicMock(return_value=[loc])

    async def mock_latest(provider_id):
        return {
            "results": [
                {"sensorsId": 1, "value": 50.0, "datetime": {"utc": "2026-04-01T12:00:00Z"}}
            ]
        }
    coord.provider_adapter.get_latest_measurements = AsyncMock(side_effect=mock_latest)

    # Simulate get_bind raising an error when trying to create AuditSession
    real_get_bind = coord.db.get_bind
    def faulty_get_bind():
        raise RuntimeError("Simulated connection pool failure during audit persistence")
    coord.db.get_bind = faulty_get_bind

    status = await coord.execute()
    assert status == "FAILED", "Run must report FAILED if audit persistence fails"
    assert "Simulated connection pool failure" in str(coord.run_record.error_message)

    # Restore get_bind
    coord.db.get_bind = real_get_bind

    # Staged measurement data MUST NOT have been committed
    records = in_memory_db.scalars(select(AQIData).where(AQIData.location_name == "AuditFailStation")).all()
    assert len(records) == 0, "Staged measurements must never be committed even if audit persistence fails"


@pytest.mark.asyncio
async def test_advisory_lock_release_on_success_and_failure(in_memory_db):
    """Regression Test 7: Verify advisory lock is released on clean completion and on unexpected exception."""
    # 7A: Clean completion
    coord_clean = IngestionCoordinator(db=in_memory_db, dry_run=True)
    coord_clean._acquire_lock = AsyncMock(return_value=True)
    coord_clean._release_lock = AsyncMock()
    coord_clean._should_run_metadata_sync = AsyncMock(return_value=False)
    coord_clean._check_db_backed_hourly_budget = AsyncMock(return_value=True)
    coord_clean.planner.plan_measurement_ingestion = MagicMock(return_value=[])

    status = await coord_clean.execute()
    assert status in ("SUCCESS", "DRY_RUN")
    coord_clean._release_lock.assert_awaited_once()

    # 7B: Catastrophic exception during execution
    coord_err = IngestionCoordinator(db=in_memory_db, dry_run=True)
    coord_err._acquire_lock = AsyncMock(return_value=True)
    coord_err._release_lock = AsyncMock()
    coord_err._check_db_backed_hourly_budget = AsyncMock(return_value=True)
    coord_err._should_run_metadata_sync = AsyncMock(side_effect=RuntimeError("Unexpected unhandled coordinator error"))

    status_err = await coord_err.execute()
    assert status_err == "FAILED"
    coord_err._release_lock.assert_awaited_once()


@pytest.mark.asyncio
async def test_normal_run_persists_measurements_and_run_record(in_memory_db):
    """Regression Test 8: Verify normal (non-dry-run) ingestion commits measurements and SUCCESS status."""
    from database.models.aqi_data import AQIData

    loc = IngestionLocation(
        provider="OpenAQ", provider_location_id=8108, location_name="NormalStation",
        is_active=True, last_synced_at=datetime(2000, 1, 1),
        sensors_json=json.dumps({"1": ["pm25", "µg/m³"]})
    )
    in_memory_db.add(loc)
    in_memory_db.commit()

    coord = IngestionCoordinator(db=in_memory_db, dry_run=False)
    coord._acquire_lock = AsyncMock(return_value=True)
    coord._should_run_metadata_sync = AsyncMock(return_value=False)
    coord._check_db_backed_hourly_budget = AsyncMock(return_value=True)
    coord.planner.plan_measurement_ingestion = MagicMock(return_value=[loc])

    async def mock_latest(provider_id):
        return {
            "results": [
                {"sensorsId": 1, "value": 30.0, "datetime": {"utc": "2026-04-01T12:00:00Z"}}
            ]
        }
    coord.provider_adapter.get_latest_measurements = AsyncMock(side_effect=mock_latest)

    status = await coord.execute()
    assert status == "SUCCESS"
    assert coord.metrics.records_stored == 1

    # In database
    records = in_memory_db.scalars(select(AQIData).where(AQIData.location_name == "NormalStation")).all()
    assert len(records) == 1
    assert records[0].pm25 == 30.0

    db_run = in_memory_db.scalar(select(IngestionRun).where(IngestionRun.run_id == coord.run_id))
    assert db_run is not None
    assert db_run.status == "SUCCESS"
    assert db_run.records_stored == 1
    assert db_run.dry_run is False


@pytest.mark.asyncio
async def test_run_once_exit_code_dry_run():
    """Regression Test 9: Verify run_once.py main returns exit code 0 when dry-run reports DRY_RUN."""
    from data_sync.run_once import main

    with patch("data_sync.run_once.run_ingestion_job", new_callable=AsyncMock) as mock_job:
        mock_job.return_value = "DRY_RUN"
        code = await main(["--dry-run", "--batch-size", "5"])
        assert code == 0
        mock_job.assert_awaited_once_with(dry_run=True, limit=5)


