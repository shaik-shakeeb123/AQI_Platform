from pydantic import BaseModel, Field
from datetime import datetime
from typing import List, Optional

class PollutantRecord(BaseModel):
    pm25: Optional[float] = Field(None, ge=0.0, description="PM2.5 value in ug/m3")
    pm10: Optional[float] = Field(None, ge=0.0, description="PM10 value in ug/m3")
    no2: Optional[float] = Field(None, ge=0.0, description="NO2 value in ug/m3")
    o3: Optional[float] = Field(None, ge=0.0, description="O3 value in ug/m3")
    co: Optional[float] = Field(None, ge=0.0, description="CO value in mg/m3")
    so2: Optional[float] = Field(None, ge=0.0, description="SO2 value in ug/m3")
    temperature: Optional[float] = Field(None, description="Temperature in Celsius")
    humidity: Optional[float] = Field(None, ge=0.0, le=100.0, description="Relative humidity %")
    wind_speed: Optional[float] = Field(None, ge=0.0, description="Wind speed in m/s")
    timestamp: datetime = Field(..., description="Timestamp of the historical recording")

class PredictRequest(BaseModel):
    city: str = Field(..., description="Target city name")
    history: List[PollutantRecord] = Field(..., min_length=1, description="List of historical records")

class PredictResponse(BaseModel):
    predicted_aqi: float = Field(..., description="Predicted continuous AQI value")
    category: str = Field(..., description="AQI category (e.g. 'Satisfactory', 'Poor')")
    predicted_at: datetime = Field(..., description="Timestamp of prediction")
