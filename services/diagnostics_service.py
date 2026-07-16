from datetime import datetime, timedelta, timezone
from typing import Any, Dict
import asyncio
from api_layer.config import get_settings
from api_layer.repositories.diagnostics_repository import DiagnosticsRepository
from ml_training.config import HORIZON_MODEL_PATHS
import os
import httpx

class DiagnosticsService:
    """Service orchestrating system diagnostics checks."""

    def __init__(self, repository: DiagnosticsRepository) -> None:
        self.repository = repository

    async def get_diagnostics(self, app_state_models: Dict[str, Any], app_state_model: Any) -> dict:
        """Ping database, inspect model loading status, evaluate scheduler latency, and verify OpenAQ/Open-Meteo connections."""
        settings = get_settings()
        
        # 1. Database Connectivity
        db_connected = False
        db_error = None
        try:
            await asyncio.to_thread(self.repository.execute_ping)
            db_connected = True
        except Exception as e:
            db_error = str(e)
            
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
            
        # 3. Scheduler Status
        scheduler_status = "unknown"
        latest_sync_time = None
        try:
            latest_record = await asyncio.to_thread(self.repository.get_latest_record)
            if latest_record and latest_record.recorded_at:
                latest_sync_time = latest_record.recorded_at.isoformat()
                if datetime.utcnow().replace(tzinfo=timezone.utc) - latest_record.recorded_at.replace(tzinfo=timezone.utc) < timedelta(hours=settings.STALE_THRESHOLD_HOURS):
                    scheduler_status = "active"
                else:
                    scheduler_status = "idle/stale"
            else:
                scheduler_status = "no records found"
        except Exception as e:
            scheduler_status = f"error checking records: {str(e)}"
            
        # 4. API Connectivity
        openaq_connected = False
        openmeteo_connected = False
        
        async with httpx.AsyncClient(timeout=5.0) as client:
            # Check Open-Meteo
            try:
                res = await client.get(settings.OPEN_METEO_BASE_URL + "/forecast?latitude=13.0&longitude=80.0&current=temperature_2m")
                if res.status_code == 200:
                    openmeteo_connected = True
            except Exception:
                pass
                
            # Check OpenAQ
            try:
                res = await client.get(settings.OPENAQ_BASE_URL + "/countries", headers={"X-API-Key": settings.OPENAQ_API_KEY or ""})
                if res.status_code in [200, 401, 403]:
                    openaq_connected = True
            except Exception:
                pass
                
        return {
            "database": {
                "connected": db_connected,
                "url_configured": settings.DATABASE_URL.split("@")[-1] if "@" in settings.DATABASE_URL else settings.DATABASE_URL,
                "error": db_error
            },
            "models": models_status,
            "scheduler": {
                "status": scheduler_status,
                "latest_record_time": latest_sync_time,
                "sync_interval_seconds": settings.INGESTION_INTERVAL_SECONDS
            },
            "apis": {
                "open_meteo": {
                    "url": settings.OPEN_METEO_BASE_URL,
                    "connected": openmeteo_connected
                },
                "openaq": {
                    "url": settings.OPENAQ_BASE_URL,
                    "connected": openaq_connected
                }
            }
        }
