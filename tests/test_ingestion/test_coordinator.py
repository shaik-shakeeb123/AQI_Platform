import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime, timedelta

from data_sync.ingestion.coordinator import IngestionCoordinator
from data_sync.ingestion.models import IngestionState, IngestionRun, IngestionLocation
from database.models.aqi_data import AQIData
from api_layer.config import get_settings

@pytest.fixture
def mock_db():
    db = MagicMock()
    # Provide a scalar that returns True for lock by default
    db.execute.return_value.scalar.return_value = True
    return db

@pytest.mark.asyncio
async def test_coordinator_acquires_lock(mock_db):
    coord = IngestionCoordinator(db=mock_db, dry_run=True)
    success = await coord._acquire_lock()
    assert success is True
    assert "pg_try_advisory_lock" in str(mock_db.execute.call_args[0][0])

@pytest.mark.asyncio
async def test_coordinator_handles_lock_failure(mock_db):
    mock_db.execute.return_value.scalar.return_value = False
    coord = IngestionCoordinator(db=mock_db, dry_run=True)
    success = await coord.execute()
    assert success == "SKIPPED_LOCKED"
    assert coord.run_record is None

@pytest.mark.asyncio
async def test_coordinator_updates_watermark(mock_db):
    coord = IngestionCoordinator(db=mock_db, dry_run=True)
    coord._acquire_lock = AsyncMock(return_value=True)
    coord._should_run_metadata_sync = AsyncMock(return_value=False)
    coord._check_db_backed_hourly_budget = AsyncMock(return_value=True)
    
    # Mock planner
    coord.planner.get_watermark = MagicMock(return_value=None)
    coord.planner.plan_measurement_ingestion = MagicMock(return_value=[])
    
    await coord.execute()
    
    assert coord.run_record is not None
    assert coord.run_record.status == "SUCCESS"
    assert coord.metrics.locations_examined == 0

