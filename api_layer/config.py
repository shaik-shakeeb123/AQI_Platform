"""Application configuration using pydantic-settings.

Consolidates settings from both the backend service and the AI layer service.
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central configuration for the consolidated AQI Platform."""

    # ── Database ────────────────────────────────────────────────────────
    DATABASE_URL: str

    # ── External APIs ───────────────────────────────────────────────────
    OPENAQ_API_KEY: str
    OPENAQ_BASE_URL: str = "https://api.openaq.org/v3"
    OPEN_METEO_BASE_URL: str = "https://api.open-meteo.com/v1"
    OSRM_BASE_URL: str = "http://router.project-osrm.org"


    # ── Application ─────────────────────────────────────────────────────
    APP_NAME: str = "AQI Intelligence Platform"
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"

    # ── Security ────────────────────────────────────────────────────────
    JWT_SECRET_KEY: str
    GOOGLE_CLIENT_ID: str
    ALLOWED_ORIGINS: str = ""
    # Key required in X-Sync-Admin-Key header to access /sync/openaq-test.
    # Set this to a long random string in your Render environment variables.
    # If left empty (default), the endpoint is inaccessible.
    SYNC_ADMIN_KEY: str = ""

    # ── Scheduled Ingestion Settings ────────────────────────────────────
    INGESTION_INTERVAL_SECONDS: int = 1800
    SCHEDULED_TARGET_RECORDS: int = 1000
    SCHEDULED_BATCH_SIZE: int = 100
    LOCK_FILE_AGE_THRESHOLD_SECS: int = 3600
    
    # ── New Ingestion Configs ───────────────────────────────────────────
    MAX_PROVIDER_CONCURRENCY: int = 10
    OPENAQ_REQUESTS_PER_MINUTE: int = 45
    INGESTION_DRY_RUN: bool = False

    # Master compliance switch for live OpenAQ ingestion.
    # Default is False (disabled). Ingestion will NOT run scheduled jobs or
    # metadata sync unless an operator explicitly enables this via environment
    # variable OPENAQ_INGESTION_ENABLED=true after provider authorization.
    OPENAQ_INGESTION_ENABLED: bool = False

    # ── OpenAQ Compliance Controls ──────────────────────────────────────
    # Kill-switch for the legacy /sync/openaq-test endpoint.
    # Default is False (disabled). The endpoint MUST NOT be enabled in
    # production unless explicitly set to True via environment variable.
    # Setting this to True in production is a compliance risk — the legacy
    # path uses the ungoverned OpenAQClient without per-minute rate limiting.
    OPENAQ_LEGACY_SYNC_ENABLED: bool = False

    # Conservative hourly budget cap shared across ALL OpenAQ request paths.
    # OpenAQ documents 2,000 req/hr. We use 1,800 to leave a 10% safety
    # margin for retries, metadata sync, and unexpected overhead.
    OPENAQ_HOURLY_REQUEST_BUDGET: int = 1800

    # User-Agent header sent with every governed OpenAQ request.
    # Identifies the platform for OpenAQ's server-side logging.
    # Contact email surfaced in the User-Agent header sent with every governed
    # OpenAQ request.  Operators MUST set this to a real, monitored address so
    # OpenAQ staff can reach them if request behaviour is flagged.
    # Leave blank to use 'unknown' as the contact identifier (a startup warning
    # will be emitted to remind operators to fill this in).
    OPENAQ_CONTACT_EMAIL: str = ""

    # User-Agent header template for every governed OpenAQ request.
    # The literal {contact} token is replaced at runtime with OPENAQ_CONTACT_EMAIL.
    # Identifies the platform in OpenAQ server-side logs.
    OPENAQ_USER_AGENT: str = "AQIPlatform/1.0 (responsible-use; contact={contact})"

    # ── ML Model Configuration ──────────────────────────────────────────
    STALE_THRESHOLD_HOURS: int = 7
    CITY_AGGREGATION_METHOD: str = "average"

    MODEL_DIR: str = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "ml_training",
        "models",
    )

    @property
    def MODEL_PATH(self) -> str:
        return os.path.join(self.MODEL_DIR, "aqi_model_1h.pkl")

    model_config = SettingsConfigDict(
        env_file=os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            ".env"
        ),
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore"
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()
