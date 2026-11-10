from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional

from data_sync.models.weather_models import (
    NormalizedCurrentWeather,
    NormalizedHourlyForecast,
)


class BaseWeatherProvider(ABC):
    """Abstract base class establishing the contract for meteorological weather providers."""

    @abstractmethod
    def get_provider_name(self) -> str:
        """Return the unique human-readable name of the weather provider."""
        raise NotImplementedError

    @abstractmethod
    def get_attribution(self) -> str:
        """Return mandatory open-data attribution string for this provider."""
        raise NotImplementedError

    @abstractmethod
    async def fetch_current_weather(
        self, lat: float, lon: float
    ) -> NormalizedCurrentWeather:
        """Fetch current weather observations/forecast and return a normalized contract."""
        raise NotImplementedError

    @abstractmethod
    async def fetch_hourly_forecast(
        self, lat: float, lon: float, hours: int = 48
    ) -> List[NormalizedHourlyForecast]:
        """Fetch multi-hour forecast timeline and return normalized forecast entries."""
        raise NotImplementedError

    @abstractmethod
    def is_rate_limited(self) -> bool:
        """Check whether provider is currently under an active rate-limit cooldown."""
        raise NotImplementedError

    @abstractmethod
    def get_cooldown_remaining(self) -> float:
        """Return remaining seconds in active cooldown (0.0 if not rate-limited)."""
        raise NotImplementedError

    @abstractmethod
    def set_cooldown(self, seconds: float, reason: str = "") -> None:
        """Engage or extend the rate-limit cooldown period for this provider."""
        raise NotImplementedError

    @abstractmethod
    def get_metrics(self) -> Dict[str, Any]:
        """Return operational telemetry metrics for observability."""
        raise NotImplementedError

    @abstractmethod
    def reset_metrics(self) -> None:
        """Reset operational telemetry counters (primarily for tests)."""
        raise NotImplementedError
