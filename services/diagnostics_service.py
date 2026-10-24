from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional
import asyncio
import os
import re
import httpx
from api_layer.config import get_settings
from api_layer.repositories.diagnostics_repository import DiagnosticsRepository
from ml_training.config import HORIZON_MODEL_PATHS

class DiagnosticsService:
    """Service orchestrating system diagnostics checks."""

    def __init__(self, repository: DiagnosticsRepository) -> None:
        self.repository = repository

    def _mask_url(self, url: str) -> str:
        """Sanitize database URLs to avoid exposing credentials."""
        if not url:
            return ""
        return re.sub(r"://([^:@]+):([^@]+)@", "://***:***@", url)

    def _sanitize_error(self, err_str: Optional[str]) -> Optional[str]:
        """Strip passwords and API keys from error messages."""
        if not err_str:
            return None
        settings = get_settings()
        cleaned = err_str
        if settings.OPENAQ_API_KEY:
            cleaned = cleaned.replace(settings.OPENAQ_API_KEY, "[REDACTED_API_KEY]")
        if settings.JWT_SECRET_KEY:
            cleaned = cleaned.replace(settings.JWT_SECRET_KEY, "[REDACTED_SECRET]")
        cleaned = re.sub(r"://([^:@]+):([^@]+)@", "://***:***@", cleaned)
        cleaned = re.sub(r"(?i)(password|pwd|secret|token|key)=([^\s,;]+)", r"\1=[REDACTED]", cleaned)
        return cleaned

    async def get_diagnostics(self, app_state_models: Dict[str, Any], app_state_model: Any) -> dict:
        """Inspect system status: database connectivity, data freshness, model loading, and scheduler status.
        
        COMPLIANCE NOTE: OpenAQ is an external data provider with strict rate limits.
        Diagnostics must NOT issue direct HTTP requests to OpenAQ to preserve request budget.
        """
        settings = get_settings()
        
        # 1. Database Connectivity
        db_connected = False
        db_error = None
        try:
            await asyncio.to_thread(self.repository.execute_ping)
            db_connected = True
        except Exception as e:
            db_error = self._sanitize_error(str(e))
            
        # 2. Loaded Models & Paths
        models_status = {}
        
        # Default model
        models_status["default"] = {
            "loaded": app_state_model is not None,
            "path": settings.MODEL_PATH,
            "exists": os.path.exists(settings.MODEL_PATH)
        }
        
        # Multi-horizon models
        for h, path in HORIZON_MODEL_PATHS.items():
            models_status[h] = {
                "loaded": h in app_state_models and app_state_models[h] is not None,
                "path": path,
                "exists": os.path.exists(path)
            }
            
        # 3. Scheduler & Data Freshness Evaluation
        # Distinguish database health from data freshness per reliability engineering standards
        scheduler_status = "unknown"
        data_freshness_status = "unknown"
        latest_sync_time = None
        measurement_age_hours: Optional[float] = None
        
        try:
            latest_record = await asyncio.to_thread(self.repository.get_latest_record)
            if latest_record and latest_record.recorded_at:
                latest_sync_time = latest_record.recorded_at.isoformat()
                now_utc = datetime.now(timezone.utc)
                rec_utc = latest_record.recorded_at.replace(tzinfo=timezone.utc) if latest_record.recorded_at.tzinfo is None else latest_record.recorded_at
                age_delta = now_utc - rec_utc
                measurement_age_hours = round(age_delta.total_seconds() / 3600.0, 2)
                
                if age_delta < timedelta(hours=settings.STALE_THRESHOLD_HOURS):
                    data_freshness_status = "fresh"
                    scheduler_status = "active"
                else:
                    data_freshness_status = "stale"
                    scheduler_status = "idle/stale"
            else:
                data_freshness_status = "empty"
                scheduler_status = "no records found"
        except Exception as e:
            scheduler_status = f"error checking records: {self._sanitize_error(str(e))}"

        # 4. Ingestion Run Status
        latest_run_info = None
        try:
            latest_run = await asyncio.to_thread(self.repository.get_latest_ingestion_run)
            if latest_run:
                latest_run_info = {
                    "run_id": getattr(latest_run, "run_id", None),
                    "status": getattr(latest_run, "status", None),
                    "started_at": getattr(latest_run, "started_at", None).isoformat() if getattr(latest_run, "started_at", None) else None,
                    "finished_at": getattr(latest_run, "finished_at", None).isoformat() if getattr(latest_run, "finished_at", None) else None,
                    "records_stored": getattr(latest_run, "records_stored", 0),
                    "error_message": self._sanitize_error(getattr(latest_run, "error_message", None)),
                }
        except Exception:
            pass

        # 5. External API Status (Passive check — ZERO OpenAQ outbound HTTP calls)
        openmeteo_connected = False
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                res = await client.get(settings.OPEN_METEO_BASE_URL + "/forecast?latitude=13.0&longitude=80.0&current=temperature_2m")
                if res.status_code == 200:
                    openmeteo_connected = True
        except Exception:
            pass

        # OpenAQ status is reported passively to comply with terms and avoid consuming request quota
        openaq_status = {
            "url": settings.OPENAQ_BASE_URL,
            "connected": None,  # Explicitly None: no live ping made to preserve rate-limit quota
            "configured": bool(settings.OPENAQ_API_KEY),
            "governance": "governed_pipeline_only",
            "live_ping": "disabled_by_compliance_policy",
            "rate_limit_rpm": settings.OPENAQ_REQUESTS_PER_MINUTE,
            "hourly_budget": settings.OPENAQ_HOURLY_REQUEST_BUDGET,
            "note": "Routine diagnostic pings to OpenAQ are disabled to prevent unmetered quota consumption."
        }
                
        return {
            "health_summary": {
                "database_status": "healthy" if db_connected else "unhealthy",
                "data_freshness_status": data_freshness_status,
                "latest_measurement_timestamp": latest_sync_time,
                "measurement_age_hours": measurement_age_hours,
            },
            "database": {
                "connected": db_connected,
                "url_configured": self._mask_url(settings.DATABASE_URL.split("@")[-1] if "@" in settings.DATABASE_URL else settings.DATABASE_URL),
                "error": db_error
            },
            "models": models_status,
            "scheduler": {
                "status": scheduler_status,
                "data_freshness_status": data_freshness_status,
                "latest_record_time": latest_sync_time,
                "measurement_age_hours": measurement_age_hours,
                "latest_run": latest_run_info,
                "sync_interval_seconds": settings.INGESTION_INTERVAL_SECONDS
            },
            "apis": {
                "open_meteo": {
                    "url": settings.OPEN_METEO_BASE_URL,
                    "connected": openmeteo_connected
                },
                "openaq": openaq_status
            }
        }
