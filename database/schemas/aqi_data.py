"""Pydantic schemas for proof-of-concept AQI data validation."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class AQIDataValidate(BaseModel):
    """Schema for validating AQI records before database storage.

    Ensures critical fields are present and coordinates and measurements
    contain logical, non-negative values.
    """

    city: str = Field(..., min_length=1, description="City name must exist and not be empty")
    location_name: str = Field(..., min_length=1, description="Location name must exist and not be empty")
    latitude: float = Field(..., description="Latitude must exist")
    longitude: float = Field(..., description="Longitude must exist")
    pm25: Optional[float] = Field(default=None, description="Optional PM2.5 measurement value")
    pm10: Optional[float] = Field(default=None, description="Optional PM10 measurement value")
    no2: Optional[float] = Field(default=None, description="Optional NO2 measurement value")
    o3: Optional[float] = Field(default=None, description="Optional O3 measurement value")
    co: Optional[float] = Field(default=None, description="Optional CO measurement value")
    so2: Optional[float] = Field(default=None, description="Optional SO2 measurement value")
    temperature: Optional[float] = Field(default=None, description="Optional temperature value")
    humidity: Optional[float] = Field(default=None, description="Optional humidity value")
    wind_speed: Optional[float] = Field(default=None, description="Optional wind speed value")
    wind_direction: Optional[float] = Field(default=None, description="Optional wind direction in degrees (0-360)")
    precipitation: Optional[float] = Field(default=None, description="Optional precipitation value in mm")
    pressure: Optional[float] = Field(default=None, description="Optional surface pressure value in hPa")
    recorded_at: datetime = Field(..., description="Timestamp must exist")
    aqi: Optional[float] = Field(default=None, description="Optional calculated AQI value")
    aqi_category: Optional[str] = Field(default=None, description="Optional calculated AQI category")
    dominant_pollutant: Optional[str] = Field(default=None, description="Optional calculated dominant pollutant")

    @field_validator("pm25", "pm10", "no2", "o3", "co", "so2", "wind_speed", "precipitation", "pressure", "aqi")
    @classmethod
    def check_non_negative(cls, v: Optional[float]) -> Optional[float]:
        """Verify that values are not negative."""
        if v is not None and v < 0.0:
            raise ValueError("Value cannot be negative")
        return v

    @field_validator("wind_direction")
    @classmethod
    def check_wind_direction(cls, v: Optional[float]) -> Optional[float]:
        """Verify wind direction is in degrees [0, 360]."""
        if v is not None and not (0.0 <= v <= 360.0):
            raise ValueError("Wind direction must be between 0 and 360 degrees")
        return v


