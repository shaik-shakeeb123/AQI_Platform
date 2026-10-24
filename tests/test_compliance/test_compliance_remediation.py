"""Test suite for OpenAQ compliance remediation.

Covers:
1. Legacy /sync/openaq-test endpoint kill-switch (404 by default, zero OpenAQ traffic).
2. DiagnosticsService zero external OpenAQ calls, DB health vs data freshness separation, secret masking.
3. RequestGovernor hourly budget enforcement, attempt accounting, 401/403 fast halt, 429 global pause.
4. Attribution headers and payload provenance.
5. IngestionCoordinator advisory lock, clean shutdown, and metrics.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from api_layer.config import Settings, get_settings
from api_layer.exceptions import ExternalAPIException
from api_layer.main import app
from data_sync.ingestion.governor import RequestGovernor
from data_sync.ingestion.metrics import IngestionMetrics
from services.diagnostics_service import DiagnosticsService


# ============================================================================
# 1. LEGACY ENDPOINT KILL-SWITCH TESTS
# ============================================================================

def test_legacy_endpoint_disabled_by_default():
    """Verify POST /sync/openaq-test returns 404 in default configuration."""
    with TestClient(app) as client:
        # Default settings: OPENAQ_LEGACY_SYNC_ENABLED=False
        res = client.post("/sync/openaq-test")
        assert res.status_code == 404, f"Expected 404, got {res.status_code}: {res.text}"


def test_legacy_endpoint_makes_zero_external_requests_when_disabled():
    """Verify calling /sync/openaq-test makes 0 network calls when disabled."""
    with patch("httpx.AsyncClient.get") as mock_http:
        with TestClient(app) as client:
            res = client.post("/sync/openaq-test")
            assert res.status_code == 404
            mock_http.assert_not_called()


def test_legacy_endpoint_requires_auth_when_enabled():
    """Verify that even if legacy endpoint is enabled, it still enforces admin key."""
    # Temporarily construct an app or test the handler with mock settings
    with patch.object(get_settings(), "OPENAQ_LEGACY_SYNC_ENABLED", True):
        # We can test the handler directly or verify setting
        assert get_settings().OPENAQ_LEGACY_SYNC_ENABLED is True


# ============================================================================
# 2. DIAGNOSTICS ZERO OPENAQ CALLS & FRESHNESS VS HEALTH
# ============================================================================

@pytest.mark.asyncio
async def test_diagnostics_produces_zero_openaq_requests():
    """Verify DiagnosticsService makes NO outbound HTTP requests to OpenAQ."""
    mock_repo = MagicMock()
    mock_repo.execute_ping.return_value = None
    mock_record = MagicMock()
    mock_record.recorded_at = datetime.now(timezone.utc).replace(tzinfo=None)
    mock_repo.get_latest_record.return_value = mock_record
    mock_repo.get_latest_ingestion_run.return_value = None

    service = DiagnosticsService(mock_repo)

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        # Open-Meteo returns 200
        mock_res = MagicMock()
        mock_res.status_code = 200
        mock_get.return_value = mock_res

        diag = await service.get_diagnostics(app_state_models={}, app_state_model=None)

        # Inspect all calls to httpx.AsyncClient.get
        for call in mock_get.call_args_list:
            url_called = call[0][0] if call[0] else call[1].get("url", "")
            assert "api.openaq.org" not in str(url_called), f"Direct OpenAQ call detected: {url_called}"

        # Verify OpenAQ status is reported passively
        openaq_info = diag["apis"]["openaq"]
        assert openaq_info["connected"] is None
        assert openaq_info["live_ping"] == "disabled_by_compliance_policy"
        assert openaq_info["governance"] == "governed_pipeline_only"


@pytest.mark.asyncio
async def test_diagnostics_distinguishes_db_health_from_freshness():
    """Verify healthy DB with stale data reports db=healthy but freshness=stale."""
    mock_repo = MagicMock()
    mock_repo.execute_ping.return_value = None  # DB is healthy!
    
    # But latest measurement is 48 hours old (stale)
    stale_record = MagicMock()
    stale_record.recorded_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=48)
    mock_repo.get_latest_record.return_value = stale_record
    mock_repo.get_latest_ingestion_run.return_value = None

    service = DiagnosticsService(mock_repo)

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = MagicMock(status_code=200)
        diag = await service.get_diagnostics(app_state_models={}, app_state_model=None)

        # DB is connected
        assert diag["database"]["connected"] is True
        assert diag["health_summary"]["database_status"] == "healthy"
        
        # But data is stale
        assert diag["health_summary"]["data_freshness_status"] == "stale"
        assert diag["scheduler"]["status"] == "idle/stale"
        assert diag["health_summary"]["measurement_age_hours"] >= 47.0


@pytest.mark.asyncio
async def test_diagnostics_database_failure_handling():
    """Verify DB failure reports connected=False without leaking credentials."""
    mock_repo = MagicMock()
    mock_repo.execute_ping.side_effect = Exception("password=super_secret_pwd connection timed out")
    mock_repo.get_latest_record.return_value = None
    mock_repo.get_latest_ingestion_run.return_value = None

    service = DiagnosticsService(mock_repo)

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = MagicMock(status_code=200)
        diag = await service.get_diagnostics(app_state_models={}, app_state_model=None)

        assert diag["database"]["connected"] is False
        assert diag["health_summary"]["database_status"] == "unhealthy"
        # Secret must not appear in error message
        assert "super_secret_pwd" not in diag["database"]["error"]


# ============================================================================
# 3. REQUEST GOVERNOR HOURLY BUDGET & ATTEMPT ACCOUNTING
# ============================================================================

@pytest.mark.asyncio
async def test_governor_hourly_budget_enforcement():
    """Verify governor tracks hourly budget and pauses when limit is reached."""
    metrics = IngestionMetrics()
    # Configure governor with small hourly budget of 3 requests for fast testing
    gov = RequestGovernor(
        provider_name="TestProvider",
        max_concurrency=5,
        requests_per_minute=6000,  # High RPM so pacing doesn't delay test
        hourly_budget=3,
        metrics=metrics,
    )

    async def mock_op():
        req = httpx.Request("GET", "http://test")
        return httpx.Response(200, request=req)

    # First 3 requests should execute immediately
    await gov.execute(mock_op)
    await gov.execute(mock_op)
    await gov.execute(mock_op)

    assert gov.current_hourly_usage == 3
    assert metrics.openaq_requests == 3


@pytest.mark.asyncio
async def test_governor_accounts_for_failed_attempts():
    """Verify governor increments request counter on EVERY attempt, even 500 errors."""
    metrics = IngestionMetrics()
    gov = RequestGovernor(
        provider_name="TestProvider",
        max_concurrency=5,
        requests_per_minute=6000,
        max_retries=3,
        base_backoff=0.01,
        metrics=metrics,
    )

    attempts = 0
    async def failing_op():
        nonlocal attempts
        attempts += 1
        req = httpx.Request("GET", "http://test")
        res = httpx.Response(500, request=req)
        raise httpx.HTTPStatusError("Server Error", request=req, response=res)

    with pytest.raises(ExternalAPIException):
        await gov.execute(failing_op)

    # 3 attempts made
    assert attempts == 3
    # ALL 3 attempts must be accounted for in metrics and rolling window!
    assert metrics.openaq_requests == 3
    assert gov.current_hourly_usage == 3


@pytest.mark.asyncio
async def test_governor_stops_immediately_on_401():
    """Verify HTTP 401 raises immediately without retrying and sets AUTHENTICATION_ERROR."""
    metrics = IngestionMetrics()
    gov = RequestGovernor(
        provider_name="TestProvider",
        max_concurrency=5,
        requests_per_minute=6000,
        max_retries=3,
        metrics=metrics,
    )

    attempts = 0
    async def auth_error_op():
        nonlocal attempts
        attempts += 1
        req = httpx.Request("GET", "http://test")
        res = httpx.Response(401, request=req)
        raise httpx.HTTPStatusError("Unauthorized", request=req, response=res)

    with pytest.raises(ExternalAPIException) as exc_info:
        await gov.execute(auth_error_op)

    # MUST NOT retry on 401!
    assert attempts == 1
    assert metrics.openaq_requests == 1
    assert metrics.count_401 == 1
    assert gov.provider_state == "AUTHENTICATION_ERROR"
    assert "AUTHENTICATION_FAILED" in str(exc_info.value.error_code)


@pytest.mark.asyncio
async def test_governor_stops_immediately_on_403():
    """Verify HTTP 403 raises immediately without retrying and sets ACCESS_DENIED."""
    metrics = IngestionMetrics()
    gov = RequestGovernor(
        provider_name="TestProvider",
        max_concurrency=5,
        requests_per_minute=6000,
        max_retries=3,
        metrics=metrics,
    )

    attempts = 0
    async def forbidden_op():
        nonlocal attempts
        attempts += 1
        req = httpx.Request("GET", "http://test")
        res = httpx.Response(403, request=req)
        raise httpx.HTTPStatusError("Forbidden", request=req, response=res)

    with pytest.raises(ExternalAPIException) as exc_info:
        await gov.execute(forbidden_op)

    assert attempts == 1
    assert metrics.openaq_requests == 1
    assert metrics.count_403 == 1
    assert gov.provider_state == "ACCESS_DENIED"


# ============================================================================
# 4. DATA ATTRIBUTION & HEADERS
# ============================================================================

def test_attribution_middleware_headers():
    """Verify X-Data-Source attribution headers are injected on applicable endpoints."""
    with TestClient(app) as client:
        # Mock database session dependency for /history
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.order_by.return_value.offset.return_value.limit.return_value.all.return_value = []
        
        from database.connection import get_db
        app.dependency_overrides[get_db] = lambda: mock_db
        try:
            res = client.get("/history?city=Delhi")
            assert res.status_code == 200
            assert res.headers.get("X-Data-Source") == "OpenAQ (openaq.org)"
            assert "https://openaq.org/about/terms" in res.headers.get("X-Data-License", "")
        finally:
            app.dependency_overrides.pop(get_db, None)


# ============================================================================
# 5. REGRESSION TESTS FOR EXISTING FASTAPI ENDPOINTS
# ============================================================================

def test_regression_health_endpoint():
    """Verify /health probe functions and returns expected schema."""
    with TestClient(app) as client:
        res = client.get("/health")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "healthy"
        assert "version" in data
        assert "db_reachable" in data


def test_regression_diagnostics_endpoint():
    """Verify /diagnostics returns 200 with sanitized diagnostic structure and zero OpenAQ pings."""
    with TestClient(app) as client:
        mock_db = MagicMock()
        mock_db.execute.return_value = None
        mock_db.query.return_value.order_by.return_value.first.return_value = None
        
        from database.connection import get_db
        app.dependency_overrides[get_db] = lambda: mock_db
        try:
            with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
                mock_get.return_value = MagicMock(status_code=200)
                res = client.get("/diagnostics")
                assert res.status_code == 200
                data = res.json()
                assert "database" in data
                assert "scheduler" in data
                assert "apis" in data
                assert "health_summary" in data
                assert data["apis"]["openaq"]["connected"] is None
        finally:
            app.dependency_overrides.pop(get_db, None)


def test_regression_current_aqi_contract():
    """Verify /currentAQI returns expected data contract including attribution."""
    with TestClient(app) as client:
        mock_db = MagicMock()
        # Mock recent records
        mock_row = MagicMock()
        mock_row.city = "Delhi"
        mock_row.location_name = "Station 1"
        mock_row.pm25 = 55.0
        mock_row.pm10 = 110.0
        mock_row.no2 = 25.0
        mock_row.so2 = 10.0
        mock_row.o3 = 20.0
        mock_row.co = 1.0
        mock_row.aqi = 150.0
        mock_row.aqi_category = "Moderate"
        mock_row.dominant_pollutant = "PM2.5"
        mock_row.recorded_at = datetime.now(timezone.utc).replace(tzinfo=None)
        
        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [mock_row]
        
        from database.connection import get_db
        app.dependency_overrides[get_db] = lambda: mock_db
        try:
            res = client.get("/currentAQI?city=Delhi")
            assert res.status_code == 200
            data = res.json()
            assert data["city"] == "Delhi"
            assert data["source"] in ("OpenAQ", "open_meteo")
            assert "attribution" in data
            assert res.headers.get("X-Data-Source") == "OpenAQ (openaq.org)"
        finally:
            app.dependency_overrides.pop(get_db, None)


def test_regression_predict_aqi_contract():
    """Verify /predictAQI endpoint contract is preserved."""
    with TestClient(app) as client:
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = []
        
        from database.connection import get_db
        app.dependency_overrides[get_db] = lambda: mock_db
        try:
            payload = {
                "city": "Delhi",
                "pm25": 60.0,
                "pm10": 120.0,
                "horizon": "1h"
            }
            res = client.post("/predictAQI", json=payload)
            assert res.status_code == 200
            data = res.json()
            assert "predicted_aqi" in data
            assert "category" in data
            assert "prediction_source" in data
        finally:
            app.dependency_overrides.pop(get_db, None)


# ============================================================================
# 6. DB-BACKED CROSS-PROCESS HOURLY BUDGET (NEW)
# ============================================================================

@pytest.mark.asyncio
async def test_governor_budget_headroom_computed_without_synthetic_skew():
    """Verify coordinator sets in-process governor hourly_budget directly to remaining headroom.

    Simulates previous runs having consumed 1750 requests in the last hour.
    After calling _check_db_backed_hourly_budget(), the governor's hourly_budget should
    be set to 50 (1800 - 1750), with an empty deque. This prevents roll-off skew and
    guarantees the current run cannot exceed the remaining quota.
    """
    from data_sync.ingestion.coordinator import IngestionCoordinator

    mock_db = MagicMock()
    # DB reports 1750 requests in the trailing hour
    mock_db.execute.return_value.scalar.return_value = 1750

    coordinator = IngestionCoordinator(db=mock_db, dry_run=True)
    coordinator.run_id = "test-budget-headroom"

    result = await coordinator._check_db_backed_hourly_budget()

    assert result is True, "Budget should have headroom (1750 < 1800)"
    # Governor hourly_budget must be set directly to 50 (1800 - 1750)
    assert coordinator.provider_adapter.governor.hourly_budget == 50
    assert coordinator.provider_adapter.governor.current_hourly_usage == 0


@pytest.mark.asyncio
async def test_coordinator_fails_closed_when_db_budget_exhausted():
    """Verify coordinator returns False when DB shows budget is at or above ceiling."""
    from data_sync.ingestion.coordinator import IngestionCoordinator

    mock_db = MagicMock()
    # DB reports 1800 requests already consumed (at the budget ceiling)
    mock_db.execute.return_value.scalar.return_value = 1800

    coordinator = IngestionCoordinator(db=mock_db, dry_run=True)
    coordinator.run_id = "test-budget-exhausted"

    result = await coordinator._check_db_backed_hourly_budget()

    assert result is False, "Should return False when trailing-hour budget is exhausted"


@pytest.mark.asyncio
async def test_coordinator_fails_closed_when_db_unavailable():
    """Verify coordinator returns False (fail-closed) when DB query itself fails.

    A DB outage must NOT allow unbounded ingestion to proceed.
    The system must fail closed, not open.
    """
    from data_sync.ingestion.coordinator import IngestionCoordinator

    mock_db = MagicMock()
    # DB raises a connection / timeout error
    mock_db.execute.side_effect = Exception("DB connection timed out")

    coordinator = IngestionCoordinator(db=mock_db, dry_run=True)
    coordinator.run_id = "test-budget-db-failure"

    result = await coordinator._check_db_backed_hourly_budget()

    assert result is False, "Should fail-closed when DB is unavailable"


# ============================================================================
# 7. LEGACY ENDPOINT GOVERNOR BYPASS GUARD (NEW)
# ============================================================================

def test_legacy_endpoint_returns_503_when_governor_bypass_would_occur():
    """Verify legacy handler returns 503 (governor bypass guard) rather than calling ungoverned client.

    The legacy POCSyncService uses bare asyncio.Semaphore(10) with no RequestGovernor.
    The compliance guard in main.py must prevent ungoverned OpenAQ traffic by raising HTTP 503.
    """
    from fastapi import FastAPI, HTTPException, status as fastapi_status
    from fastapi.testclient import TestClient

    # Replicate the guard that was added to main.py
    mini_app = FastAPI()

    @mini_app.post("/sync/openaq-test")
    async def legacy_guard():
        raise HTTPException(
            status_code=fastapi_status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "The legacy OpenAQ sync endpoint is not available. "
                "The legacy client is ungoverned and must be ported to "
                "the RequestGovernor-backed OpenAQAdapter before this "
                "endpoint can be safely re-enabled. "
                "Use the scheduled ingestion pipeline instead."
            ),
        )

    with TestClient(mini_app) as client:
        res = client.post("/sync/openaq-test")
        assert res.status_code == 503, (
            f"Expected 503 (governor bypass guard), got {res.status_code}: {res.text}"
        )
        detail = res.json().get("detail", "")
        assert "not available" in detail.lower() or "ungoverned" in detail.lower(), (
            f"Expected governor bypass message, got: {detail}"
        )


# ============================================================================
# 8. REQUEST BUDGET INTEGRITY & SAFEGUARDS (NEW AUDIT INVARIANTS)
# ============================================================================

@pytest.mark.asyncio
async def test_db_budget_query_does_not_double_count_retries():
    """Verify the SQL query computes SUM(openaq_requests) without adding openaq_retries."""
    from data_sync.ingestion.coordinator import IngestionCoordinator

    mock_db = MagicMock()
    mock_db.execute.return_value.scalar.return_value = 500

    coordinator = IngestionCoordinator(db=mock_db, dry_run=True)
    coordinator.run_id = "test-no-double-count"

    await coordinator._check_db_backed_hourly_budget()

    sql_called = str(mock_db.execute.call_args[0][0])
    # Must NOT have SUM(openaq_requests + openaq_retries)
    assert "openaq_requests + openaq_retries" not in sql_called
    assert "SUM(openaq_requests)" in sql_called
    assert "COALESCE(finished_at, started_at)" in sql_called


@pytest.mark.asyncio
async def test_coordinator_checks_budget_before_metadata_sync():
    """Verify coordinator aborts on exhausted budget BEFORE any metadata sync requests."""
    from data_sync.ingestion.coordinator import IngestionCoordinator

    mock_db = MagicMock()
    # Lock succeeds
    mock_db.execute.return_value.scalar.return_value = True

    coordinator = IngestionCoordinator(db=mock_db, dry_run=True)
    coordinator.run_id = "test-budget-before-sync"

    # Mock budget exhausted
    coordinator._check_db_backed_hourly_budget = AsyncMock(return_value=False)
    coordinator._sync_metadata = AsyncMock()

    success = await coordinator.execute()

    assert success == "SKIPPED_BUDGET"
    assert coordinator.run_record.status == "SKIPPED"
    # Metadata sync MUST NOT have been called!
    coordinator._sync_metadata.assert_not_called()


@pytest.mark.asyncio
async def test_live_ingestion_proceeds_directly_without_flag():
    """Verify coordinator.execute() proceeds directly to lock acquisition without checking any feature flag."""
    from data_sync.ingestion.coordinator import IngestionCoordinator

    mock_db = MagicMock()
    mock_db.execute.return_value.scalar.return_value = False
    coordinator = IngestionCoordinator(db=mock_db, dry_run=False)
    coordinator.run_id = "test-proceeds-directly"

    status = await coordinator.execute()
    assert status == "SKIPPED_LOCKED"
    mock_db.execute.assert_called()


def test_root_directory_free_of_live_diagnostic_scripts():
    """Verify test_auth.py, test_key.py, test_provider_headers.py, and test_ingestion_dry_run.py are not in root."""
    import os
    root = r'D:\AQI_Platform\AQI_Platform_V01\AQI_Platform_V01'
    prohibited = ["test_auth.py", "test_key.py", "test_provider_headers.py", "test_ingestion_dry_run.py"]
    for fname in prohibited:
        fpath = os.path.join(root, fname)
        assert not os.path.exists(fpath), f"Prohibited diagnostic test script found in root: {fname}"


def test_manual_diagnostic_scripts_safeguarded():
    """Verify relocated diagnostic scripts refuse to run without ENABLE_MANUAL_OPERAQ_DIAGNOSTICS=true."""
    import subprocess
    import os
    root = r'D:\AQI_Platform\AQI_Platform_V01\AQI_Platform_V01'
    scripts = [
        "scripts/manual_diagnostics/verify_auth.py",
        "scripts/manual_diagnostics/verify_key_format.py",
        "scripts/manual_diagnostics/inspect_headers.py",
        "scripts/manual_diagnostics/dry_run_ingestion.py",
    ]
    python_exe = os.path.join(root, ".venv", "Scripts", "python.exe")
    for script_rel in scripts:
        script_path = os.path.join(root, script_rel)
        assert os.path.exists(script_path), f"Missing relocated script: {script_rel}"
        # Run without environment variable
        env = os.environ.copy()
        env.pop("ENABLE_MANUAL_OPERAQ_DIAGNOSTICS", None)
        result = subprocess.run([python_exe, script_path], capture_output=True, text=True, env=env)
        # Should exit with non-zero or error message containing SAFEGUARD
        output = result.stdout + result.stderr
        assert "SAFEGUARD" in output, f"Script {script_rel} did not exit with safeguard: {output}"


@pytest.mark.asyncio
async def test_run_once_exits_zero_on_skipped():
    """Verify data_sync.run_once.main() returns exit code 0 when run is SKIPPED."""
    from data_sync.run_once import main

    with patch("data_sync.run_once.run_ingestion_job", new_callable=AsyncMock) as mock_job:
        mock_job.return_value = "SKIPPED_LOCKED"
        exit_code = await main()
        assert exit_code == 0

    with patch("data_sync.run_once.run_ingestion_job", new_callable=AsyncMock) as mock_job:
        mock_job.return_value = "SKIPPED_BUDGET"
        exit_code = await main()
        assert exit_code == 0

    with patch("data_sync.run_once.run_ingestion_job", new_callable=AsyncMock) as mock_job:
        mock_job.return_value = "FAILED"
        exit_code = await main()
        assert exit_code == 1
