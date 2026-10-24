import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime

from sqlalchemy import select, func
from data_sync.ingestion.models import IngestionLocation, IngestionRun
from data_sync.ingestion.coordinator import IngestionCoordinator

@pytest.mark.asyncio
async def test_coordinator_cancellation_safety(db_session):
    now = datetime.now()
    loc_a = IngestionLocation(provider="Test", provider_location_id=101, location_name="Station_Cancel_A", is_active=True, last_successful_ingestion_at=now.replace(year=2000), last_synced_at=now.replace(year=2000))
    loc_b = IngestionLocation(provider="Test", provider_location_id=102, location_name="Station_Cancel_B", is_active=True, last_successful_ingestion_at=now.replace(year=2000), last_synced_at=now.replace(year=2000))
    
    db_session.add_all([loc_a, loc_b])
    db_session.commit()
    
    coordinator = IngestionCoordinator(db_session, dry_run=False)
    coordinator.provider = "Test"
    
    coordinator.planner.plan_measurement_ingestion = MagicMock(return_value=[loc_a, loc_b])
    
    async def mock_get_latest(provider_id):
        await asyncio.sleep(0.1) # Simulate network delay
        return {"results": [{"parameter": {"name": "pm25"}, "value": 10, "date": {"utc": "2026-01-01T10:00:00Z"}}]}
    coordinator.provider_adapter.get_latest_measurements = AsyncMock(side_effect=mock_get_latest)
    
    coordinator._acquire_lock = AsyncMock(return_value=True)
    coordinator._should_run_metadata_sync = AsyncMock(return_value=False)
    coordinator._check_db_backed_hourly_budget = AsyncMock(return_value=True)
    
    task = asyncio.create_task(coordinator.execute())
    await asyncio.sleep(0.05)  # Let it start
    task.cancel()  # Cancel it mid-flight before DB writer commits (batch size 25 not reached)
    
    try:
        await task
    except asyncio.CancelledError:
        pass
        
    db_session.refresh(loc_a)
    db_session.refresh(loc_b)
    
    from database.models.aqi_data import AQIData
    count = db_session.query(func.count(AQIData.id)).filter(AQIData.location_name.in_(["Station_Cancel_A", "Station_Cancel_B"])).scalar()
    
    # Ensure no data was committed!
    assert count == 0
    # Ensure checkpoints are NOT advanced!
    assert loc_a.last_successful_ingestion_at.year == 2000
    assert loc_b.last_successful_ingestion_at.year == 2000
    
    # Ensure run status is CANCELLED
    run = db_session.scalar(select(IngestionRun).where(IngestionRun.run_id == coordinator.run_id))
    assert run.status == "CANCELLED"
