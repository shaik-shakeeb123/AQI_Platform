"""Centralized WMO Weather Code Mapping.

Maps WMO weather interpretation codes (used by Open-Meteo) to human-readable
condition strings, descriptions, and icon identifiers compatible with the
OpenWeatherMap icon convention.

Reference: https://open-meteo.com/en/docs#weathervariables
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class WeatherCondition:
    """Immutable representation of a decoded weather condition."""

    main: str
    description: str
    icon: str


# ── WMO Code Mapping Table ─────────────────────────────────────────────────
# Source: WMO Weather interpretation codes (WW)
# https://open-meteo.com/en/docs

_WMO_CODE_MAP: dict[int, WeatherCondition] = {
    # Clear sky
    0: WeatherCondition(main="Clear", description="clear sky", icon="01d"),

    # Mainly clear
    1: WeatherCondition(main="Clear", description="mainly clear", icon="01d"),

    # Partly cloudy
    2: WeatherCondition(main="Clouds", description="partly cloudy", icon="02d"),

    # Overcast
    3: WeatherCondition(main="Clouds", description="overcast clouds", icon="04d"),

    # Fog
    45: WeatherCondition(main="Fog", description="fog", icon="50d"),
    48: WeatherCondition(main="Fog", description="depositing rime fog", icon="50d"),

    # Drizzle
    51: WeatherCondition(main="Drizzle", description="light drizzle", icon="09d"),
    53: WeatherCondition(main="Drizzle", description="moderate drizzle", icon="09d"),
    55: WeatherCondition(main="Drizzle", description="dense drizzle", icon="09d"),

    # Freezing drizzle
    56: WeatherCondition(main="Drizzle", description="light freezing drizzle", icon="09d"),
    57: WeatherCondition(main="Drizzle", description="dense freezing drizzle", icon="09d"),

    # Rain
    61: WeatherCondition(main="Rain", description="slight rain", icon="10d"),
    63: WeatherCondition(main="Rain", description="moderate rain", icon="10d"),
    65: WeatherCondition(main="Rain", description="heavy rain", icon="10d"),

    # Freezing rain
    66: WeatherCondition(main="Rain", description="light freezing rain", icon="10d"),
    67: WeatherCondition(main="Rain", description="heavy freezing rain", icon="10d"),

    # Snow
    71: WeatherCondition(main="Snow", description="slight snow", icon="13d"),
    73: WeatherCondition(main="Snow", description="moderate snow", icon="13d"),
    75: WeatherCondition(main="Snow", description="heavy snow", icon="13d"),
    77: WeatherCondition(main="Snow", description="snow grains", icon="13d"),

    # Rain showers
    80: WeatherCondition(main="Rain", description="slight rain showers", icon="09d"),
    81: WeatherCondition(main="Rain", description="moderate rain showers", icon="09d"),
    82: WeatherCondition(main="Rain", description="violent rain showers", icon="09d"),

    # Snow showers
    85: WeatherCondition(main="Snow", description="slight snow showers", icon="13d"),
    86: WeatherCondition(main="Snow", description="heavy snow showers", icon="13d"),

    # Thunderstorm
    95: WeatherCondition(main="Thunderstorm", description="thunderstorm", icon="11d"),
    96: WeatherCondition(main="Thunderstorm", description="thunderstorm with slight hail", icon="11d"),
    99: WeatherCondition(main="Thunderstorm", description="thunderstorm with heavy hail", icon="11d"),
}

_DEFAULT_CONDITION = WeatherCondition(
    main="Clear",
    description="clear sky",
    icon="01d",
)


def decode_weather_code(code: Optional[int]) -> WeatherCondition:
    """Decode a WMO weather interpretation code into a WeatherCondition.

    Args:
        code: WMO weather code (0-99), or None if unavailable.

    Returns:
        A WeatherCondition with ``main``, ``description``, and ``icon`` fields.
        Falls back to the default "Clear" condition for unknown or missing codes.
    """
    if code is None:
        return _DEFAULT_CONDITION
    return _WMO_CODE_MAP.get(code, _DEFAULT_CONDITION)
