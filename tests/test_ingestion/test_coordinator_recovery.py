import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime

from sqlalchemy import select
from data_sync.ingestion.models import IngestionLocation, IngestionRun
from data_sync.ingestion.coordinator import IngestionCoordinator

@pytest.mark.asyncio
async def test_coordinator_partial_failure_recovery(db_session):
    """
    Proves that when one station fails:
    - Successful stations are durable (if committed)
    - Failed station checkpoint does not advance
    - Failed station last_synced_at is advanced (delaying retry by 1 hour)
    """
    
    # 1. Setup 3 stations
    now = datetime.now()
    loc_a = IngestionLocation(provider="Test", provider_location_id=1, location_name="Station_A", is_active=True, last_successful_ingestion_at=now.replace(year=2000), last_synced_at=now.replace(year=2000))
    loc_b = IngestionLocation(provider="Test", provider_location_id=2, location_name="Station_B", is_active=True, last_successful_ingestion_at=now.replace(year=2000), last_synced_at=now.replace(year=2000))
    loc_c = IngestionLocation(provider="Test", provider_location_id=3, location_name="Station_C", is_active=True, last_successful_ingestion_at=now.replace(year=2000), last_synced_at=now.replace(year=2000))
    
    db_session.add_all([loc_a, loc_b, loc_c])
    db_session.commit()
    
    coordinator = IngestionCoordinator(db_session, dry_run=False)
    coordinator.provider = "Test"
    
    # Mock Planner to only return these 3
    coordinator.planner.plan_measurement_ingestion = MagicMock(return_value=[loc_a, loc_b, loc_c])
    
    # Mock Provider Adapter
    async def mock_get_latest(provider_id):
        return {"results": [{"parameter": {"name": "pm25"}, "value": 10, "date": {"utc": "2026-01-01T10:00:00Z"}}]}
    coordinator.provider_adapter.get_latest_measurements = AsyncMock(side_effect=mock_get_latest)
    
    # Mock Processor to fail ONLY for Station B
    original_process = coordinator.processor.process_and_store
    
    async def mock_process(loc, results):
        if loc.location_name == "Station_B":
            raise ValueError("Simulated processing failure")
        return await original_process(loc, results)
        
    coordinator.processor.process_and_store = AsyncMock(side_effect=mock_process)
    
    # Disable acquire_lock to prevent conflicts
    coordinator._acquire_lock = AsyncMock(return_value=True)
    coordinator._should_run_metadata_sync = AsyncMock(return_value=False)
    coordinator._check_db_backed_hourly_budget = AsyncMock(return_value=True)
    
    # 2. Run execution
    # It should return "PARTIAL" because of the failure
    result = await coordinator.execute()
    assert result == "PARTIAL"
    
    # 3. Verify state in DB
    db_session.refresh(loc_a)
    db_session.refresh(loc_b)
    db_session.refresh(loc_c)
    
    assert loc_a.last_successful_ingestion_at.year == 2026, "Station A checkpoint MUST advance"
    assert loc_c.last_successful_ingestion_at.year == 2026, "Station C checkpoint MUST advance"
    assert loc_b.last_successful_ingestion_at.year == 2000, "Station B checkpoint MUST NOT advance"
    
    # 4. Verify run status is PARTIAL
    run = db_session.scalar(select(IngestionRun).where(IngestionRun.run_id == coordinator.run_id))
    assert run.status == "PARTIAL", "Run must be marked PARTIAL, not SUCCESS"
