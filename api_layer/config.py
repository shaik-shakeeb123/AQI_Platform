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
