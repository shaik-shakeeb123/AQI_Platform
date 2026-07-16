"""AQI Intelligence Platform — Consolidated FastAPI application entry-point.

Creates the FastAPI application, loads the LightGBM model, registers exception handlers,
includes API routers, and configures middleware.
"""

from __future__ import annotations

import os
import joblib
from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator
from typing import Any

import re
from fastapi import FastAPI, Depends, Header, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from api_layer.config import get_settings
from database.connection import init_db, get_db
from api_layer.exceptions import (
    AppException,
    app_exception_handler,
    generic_exception_handler,
)
from api_layer.logging import configure_logging, get_logger

# ── Logging (configure as early as possible) ────────────────────────────────
configure_logging()
logger = get_logger(__name__)

settings = get_settings()


# ── Lifespan ────────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan: runs setup before accepting requests and
    teardown after shutdown signal.
    """
    logger.info("Starting %s …", settings.APP_NAME)
    

    # Schema is managed exclusively via Alembic migrations.

    # 1. Load default pre-trained LightGBM model
    model_path = settings.MODEL_PATH
    if os.path.exists(model_path):
        try:
            logger.info(f"Loading LightGBM model from {model_path}...")
            app.state.model = joblib.load(model_path)
            app.state.model_loaded = True
            logger.info("Model loaded successfully into state.")
        except Exception as e:
            logger.error(f"Failed to load default LightGBM model at startup: {e}")
            app.state.model = None
            app.state.model_loaded = False
    else:
        logger.warning(
            f"Pre-trained model file not found at '{model_path}'. "
            "Model will operate in fallback heuristic mode."
        )
        app.state.model = None
        app.state.model_loaded = False

    # 2. Load multi-horizon models
    app.state.models = {}
    from ml_training.config import HORIZON_MODEL_PATHS
    for h, m_path in HORIZON_MODEL_PATHS.items():
        if os.path.exists(m_path):
            try:
                logger.info(f"Loading LightGBM model for horizon {h} from {m_path}...")
                app.state.models[h] = joblib.load(m_path)
            except Exception as e:
                logger.error(f"Failed to load LightGBM model for horizon {h}: {e}")
        else:
            logger.warning(f"LightGBM model for horizon {h} not found at '{m_path}'.")

    # Set model_loaded based on whether any model (default or horizon) is available
    if not app.state.model_loaded:
        app.state.model_loaded = bool(app.state.models)

    yield
    # --- Shutdown: release all persistent HTTP client sockets ---
    _clients_to_close = [
        ("Nominatim",        "data_sync.clients.nominatim_client"),
        ("OpenMeteo AQ",     "data_sync.clients.openmeteo_air_quality_client"),
        ("OpenMeteo Weather","data_sync.clients.openmeteo_weather_client"),
        ("OSRM",             "data_sync.clients.osrm_client"),
    ]
    for _name, _mod_path in _clients_to_close:
        try:
            import importlib
            _mod = importlib.import_module(_mod_path)
            _cli = getattr(_mod, "_client", None)
            if _cli is not None and not _cli.is_closed:
                await _cli.aclose()
                logger.info("%s HTTP client closed.", _name)
        except Exception as _e:
            logger.warning("Error closing %s client on shutdown: %s", _name, _e)
    logger.info("Shutting down %s …", settings.APP_NAME)


# ── Application factory ────────────────────────────────────────────────────

app = FastAPI(
    title=settings.APP_NAME,
    description=(
        "Consolidated backend service for real-time air quality monitoring, data "
        "aggregation from OpenAQ and Open-Meteo, and local AQI analytics."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# ── Exception handlers ─────────────────────────────────────────────────────
app.add_exception_handler(AppException, app_exception_handler)  # type: ignore[arg-type]
app.add_exception_handler(Exception, generic_exception_handler)  # type: ignore[arg-type]

# ── Middleware ──────────────────────────────────────────────────────────────
allowed_origins = [o.strip() for o in settings.ALLOWED_ORIGINS.split(",") if o.strip()]
# FastAPI raises a RuntimeError at startup if allow_origins=["*"] is combined
# with allow_credentials=True.  Detect that illegal combination and disable
# credentials automatically so the application can still start.
_has_wildcard_origin = "*" in allowed_origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=not _has_wildcard_origin,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Rate Limiting Middleware ────────────────────────────────────────────────
# Zero-dependency, in-process rate limiter protecting the auth endpoints.
# Limits each remote IP to AUTH_RATE_LIMIT_PER_MINUTE requests/minute on
# /auth/login and /auth/register.  Uses a sliding-window counter keyed by
# (ip, endpoint_prefix, current_minute_bucket) so memory footprint stays O(1).
from api_layer.rate_limiter import AuthRateLimitMiddleware  # noqa: E402
app.add_middleware(AuthRateLimitMiddleware, max_requests=10)

# ── Routers ─────────────────────────────────────────────────────────────────
from api_layer.api.routes.aqi import router as aqi_router  # noqa: E402
from api_layer.api.routes.auth import router as auth_router  # noqa: E402

app.include_router(aqi_router)
app.include_router(auth_router, prefix="/auth", tags=["Authentication"])

from fastapi.staticfiles import StaticFiles
frontend_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend")
if os.path.isdir(frontend_dir):
    app.mount("/static", StaticFiles(directory=frontend_dir), name="static")



# ── Proof of Concept Ingestion ──────────────────────────────────────────────


@app.post("/sync/openaq-test", tags=["Proof of Concept Ingestion"])
async def sync_openaq_test(
    target_records: int = 100,
    batch_size: int = 20,
    db: Session = Depends(get_db),
    x_sync_admin_key: str = Header(default="", alias="X-Sync-Admin-Key"),
) -> dict[str, Any]:
    """Trigger a minimal proof-of-concept AQI data collection run.

    Requires the ``X-Sync-Admin-Key`` header to match the ``SYNC_ADMIN_KEY``
    environment variable.  Set ``SYNC_ADMIN_KEY`` in your Render environment
    variables to a long random string.
    """
    sync_key = settings.SYNC_ADMIN_KEY
    if not sync_key or x_sync_admin_key != sync_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing X-Sync-Admin-Key header.",
        )
    from data_sync.sync_service import POCSyncService
    service = POCSyncService(db)
    return await service.sync_openaq_test(target_records=target_records, batch_size=batch_size)


# ── Health check ────────────────────────────────────────────────────────────


@app.get("/health", tags=["Health"])
async def health_check() -> dict[str, Any]:
    """Liveness + shallow readiness probe.

    Returns ``{"status": "healthy"}`` when the application process is running
    and the database connection pool can reach the server.  If the database is
    unreachable the endpoint still returns HTTP 200 (so the process is not
    killed) but sets ``db_reachable`` to ``False`` so operators can observe
    the degraded state.
    """
    import asyncio as _asyncio
    from database.connection import engine as _engine

    db_ok = False
    try:
        # Run the synchronous pool ping in the thread pool to avoid blocking.
        def _ping():
            with _engine.connect() as conn:
                conn.execute(__import__("sqlalchemy").text("SELECT 1"))
        await _asyncio.to_thread(_ping)
        db_ok = True
    except Exception as _exc:
        logger.warning("Health check DB ping failed: %s", _exc)

    return {
        "status": "healthy",
        "app": settings.APP_NAME,
        "version": "1.0.0",
        "model_loaded": getattr(app.state, "model_loaded", False),
        "db_reachable": db_ok,
    }
