from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Optional, Any, Dict, List


def calculate_apparent_temperature(
    temp_c: float,
    humidity_pct: float,
    wind_speed_ms: float = 0.0
) -> float:
    """Calculate Australian Bureau of Meteorology Steadman Apparent Temperature.
    
    Formula:
      e = (humidity_pct / 100.0) * 6.105 * exp(17.27 * temp_c / (237.7 + temp_c))
      AT = temp_c + 0.33 * e - 0.70 * wind_speed_ms - 4.00
    """
    try:
        vp = (humidity_pct / 100.0) * 6.105 * math.exp(
            (17.27 * temp_c) / (237.7 + temp_c)
        )
        at = temp_c + (0.33 * vp) - (0.70 * wind_speed_ms) - 4.00
        return round(at, 1)
    except Exception:
        return round(temp_c, 1)


def calculate_solar_times(
    lat: float,
    lon: float,
    dt: Optional[datetime] = None
) -> tuple[Optional[datetime], Optional[datetime]]:
    """Calculate approximate sunrise and sunset in UTC using NOAA solar equations."""
    try:
        if dt is None:
            dt = datetime.now(timezone.utc)
        elif dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
            
        day_of_year = dt.timetuple().tm_yday
        gamma = 2.0 * math.pi / 365.0 * (day_of_year - 1 + (dt.hour - 12) / 24.0)
        
        eqtime = 229.18 * (
            0.000075
            + 0.001868 * math.cos(gamma)
            - 0.032077 * math.sin(gamma)
            - 0.014615 * math.cos(2 * gamma)
            - 0.040849 * math.sin(2 * gamma)
        )
        
        decl = (
            0.006918
            - 0.399912 * math.cos(gamma)
            + 0.070257 * math.sin(gamma)
            - 0.006758 * math.cos(2 * gamma)
            + 0.000907 * math.sin(2 * gamma)
            - 0.002697 * math.cos(3 * gamma)
            + 0.00148 * math.sin(3 * gamma)
        )
        
        lat_rad = math.radians(lat)
        zenith_rad = math.radians(90.833)  # Official atmospheric refraction zenith
        
        cos_ha = (math.cos(zenith_rad) / (math.cos(lat_rad) * math.cos(decl))) - (
            math.tan(lat_rad) * math.tan(decl)
        )
        if cos_ha > 1.0 or cos_ha < -1.0:
            return None, None  # Polar day or polar night
            
        ha_deg = math.degrees(math.acos(cos_ha))
        
        sunrise_min = 720.0 - 4.0 * (lon + ha_deg) - eqtime
        sunset_min = 720.0 - 4.0 * (lon - ha_deg) - eqtime
        
        base_date = datetime(dt.year, dt.month, dt.day, tzinfo=timezone.utc)
        sunrise_dt = base_date + timedelta(minutes=sunrise_min)
        sunset_dt = base_date + timedelta(minutes=sunset_min)
        return sunrise_dt, sunset_dt
    except Exception:
        return None, None


@dataclass
class NormalizedCurrentWeather:
    """Provider-independent internal representation of current meteorological conditions."""
    temperature: Optional[float] = None
    feels_like: Optional[float] = None
    humidity: Optional[float] = None
    wind_speed: Optional[float] = None  # in km/h
    wind_direction: Optional[float] = None  # degrees (0-360)
    pressure: Optional[float] = None  # in hPa
    precipitation: Optional[float] = None  # in mm
    cloud_cover: Optional[float] = None  # in %
    weather_code: Optional[int] = None
    condition: Optional[str] = None
    condition_description: Optional[str] = None
    condition_icon: Optional[str] = None
    sunrise: Optional[str] = None
    sunset: Optional[str] = None
    sunrise_timestamp: Optional[int] = None
    sunset_timestamp: Optional[int] = None
    recorded_at: Optional[datetime] = None
    provider: str = "Unknown"
    source: str = "LIVE"
    attribution: str = ""
    is_available: bool = True
    cached_at: Optional[str] = None
    cooldown_remaining_seconds: Optional[float] = None
    raw_data: Dict[str, Any] = field(default_factory=dict)

    def to_legacy_dict(self) -> Dict[str, Any]:
        """Convert to legacy format expected by DataProcessor.merge_weather and current_aqi_service."""
        return {
            "current": {
                "temperature_2m": self.temperature,
                "relative_humidity_2m": self.humidity,
                "apparent_temperature": self.feels_like,
                "wind_speed_10m": self.wind_speed,
                "wind_direction_10m": self.wind_direction,
                "surface_pressure": self.pressure,
                "precipitation": self.precipitation,
                "weather_code": self.weather_code,
                "cloud_cover": self.cloud_cover,
                "time": self.recorded_at.isoformat() if self.recorded_at else None,
            },
            "daily": {
                "sunrise": [self.sunrise] if self.sunrise else [],
                "sunset": [self.sunset] if self.sunset else [],
            },
            "provider": self.provider,
            "source": self.source,
            "attribution": self.attribution,
            "is_available": self.is_available,
            "cached_at": self.cached_at,
            "cooldown_remaining_seconds": self.cooldown_remaining_seconds,
        }


@dataclass
class NormalizedHourlyForecast:
    """Provider-independent internal representation of an hourly forecast entry."""
    timestamp: datetime
    temperature: Optional[float] = None
    humidity: Optional[float] = None
    wind_speed: Optional[float] = None  # in km/h
    wind_direction: Optional[float] = None
    precipitation: Optional[float] = None
    pressure: Optional[float] = None
    cloud_cover: Optional[float] = None
    condition: Optional[str] = None
    weather_code: Optional[int] = None
    provider: str = "Unknown"
