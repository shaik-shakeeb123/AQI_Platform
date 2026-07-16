"""

These schemas are designed to be simple, self-explanatory, and direct.
"""

from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field


class AQIMeasurementResponse(BaseModel):
    """Pydantic response schema representing an AQI data record.
    
    This matches the attributes of the AQIData database model.
    """
    id: int
    city: str
    location_name: str
    latitude: float
    longitude: float
    pm25: Optional[float] = None
    pm10: Optional[float] = None
    no2: Optional[float] = None
    o3: Optional[float] = None
    co: Optional[float] = None
    so2: Optional[float] = None
    temperature: Optional[float] = None
    humidity: Optional[float] = None
    wind_speed: Optional[float] = None
    wind_direction: Optional[float] = None
    precipitation: Optional[float] = None
    pressure: Optional[float] = None
    recorded_at: datetime

    model_config = {
        "from_attributes": True  # Allows Pydantic to read ORM objects directly
    }


class PredictAQIRequest(BaseModel):
    """Pydantic request body schema for mock AQI prediction.
    
    Accepts the target city and optional overrides.
    """
    city: str = Field(..., min_length=1, description="Target city to run the AQI forecast on")
    pm25: Optional[float] = Field(default=None, ge=0.0, description="Optional override PM2.5 concentration in ug/m3")
    pm10: Optional[float] = Field(default=None, ge=0.0, description="Optional override PM10 concentration in ug/m3")
    no2: Optional[float] = Field(default=None, ge=0.0, description="Optional override NO2 concentration in ug/m3")
    o3: Optional[float] = Field(default=None, ge=0.0, description="Optional override O3 concentration in ug/m3")
    co: Optional[float] = Field(default=None, ge=0.0, description="Optional override CO concentration in mg/m3")
    so2: Optional[float] = Field(default=None, ge=0.0, description="Optional override SO2 concentration in ug/m3")
    temperature: Optional[float] = Field(default=None, description="Optional override temperature in Celsius")
    humidity: Optional[float] = Field(default=None, ge=0.0, le=100.0, description="Optional override relative humidity percentage")
    horizon: Optional[str] = Field(default="1h", description="Forecast horizon ('1h', '3h', '6h', '12h', '24h')")


class PredictAQIResponse(BaseModel):
    """Pydantic response schema for mock AQI prediction.
    
    Returns mocked outputs to demonstrate future AI capabilities.
    """
    predicted_aqi: Optional[float] = Field(default=None, description="Mocked predicted AQI value")
    category: Optional[str] = Field(default=None, description="AQI category (e.g., Good, Moderate, Unhealthy)")
    predicted_at: datetime = Field(default_factory=datetime.utcnow, description="Prediction timestamp")
    prediction_source: str = Field(default="ml-model", description="Source of the prediction (e.g. 'ml-model', 'insufficient-data')")
    message: Optional[str] = Field(default=None, description="Detailed explanation if prediction is unavailable")


class HealthInsightsResponse(BaseModel):
    """Pydantic response schema for health recommendations.
    
    Returns specific advice and risk warnings.
    """
    city: str
    current_aqi: float
    status: str
    risk_level: str
    recommendations: List[str] = Field(..., description="Actionable health tips")
    safety_warnings: List[str] = Field(..., description="Specific warnings for vulnerable groups")
    source: str = Field(default="database", description="Telemetry data source")


class SafeWindowRequest(BaseModel):
    """Pydantic request body schema to identify the safest outdoor window."""
    city: str = Field(..., min_length=1, description="Target city to find the safe outdoor window")


class SafeWindowResponse(BaseModel):
    """Pydantic response schema returning the safest forecasted outdoor hours."""
    city: str = Field(..., description="Target city name")
    safe_window_start: str = Field(..., description="ISO 8601 start timestamp of the safest outdoor window")
    safe_window_end: str = Field(..., description="ISO 8601 end timestamp of the safest outdoor window")
    duration_hours: float = Field(..., description="Duration of the safe window in hours")
    predicted_aqi: float = Field(..., description="Predicted average AQI during this window")
    safety_level: str = Field(..., description="AQI safety category (e.g. 'Good', 'Moderate')")
    weather_condition: str = Field(..., description="Forecasted weather condition (e.g. 'Clear')")
    recommendations: List[str] = Field(..., description="Actionable safety guidelines for this window")


class RouteOptimizationRequest(BaseModel):
    """Pydantic request body schema for healthy route optimization."""
    city: Optional[str] = Field(default=None, description="Optional city context for routing")
    start_point: str = Field(..., min_length=1, description="Starting point/street/neighborhood")
    destination: str = Field(..., min_length=1, description="Destination point/street/neighborhood")
    diagnostics: Optional[bool] = Field(default=None, description="Include detailed diagnostics in response")


class RouteSegment(BaseModel):
    color: str = Field(..., description="AQI segment color ('green', 'yellow', 'red')")
    coordinates: List[List[float]] = Field(..., description="Segment coordinate list")

class StationMetadata(BaseModel):
    name: Optional[str] = Field(default=None, description="Monitoring station name")
    distance_km: Optional[float] = Field(default=None, description="Distance from the query point to the station in kilometers")
    recorded_at: Optional[datetime] = Field(default=None, description="Timestamp of the selected AQI record")
    age_hours: Optional[float] = Field(default=None, description="Age of the telemetry data in hours")
    data_status: str = Field(..., description="Status of the data source ('fresh', 'stale', 'fallback')")

class DataQualityMetrics(BaseModel):
    fresh_station_count: int = Field(..., description="Number of fresh stations used")
    stale_station_count: int = Field(..., description="Number of stale stations used")
    fallback_points: int = Field(..., description="Number of route points using fallback data")
    average_station_age_hours: Optional[float] = Field(default=None, description="Average age of the stations in hours")

class RouteOption(BaseModel):
    """Pydantic sub-schema representing a single optimized route option."""
    route_name: str = Field(..., description="Descriptive name of the route (e.g. 'Eco Route')")
    distance_km: float = Field(..., description="Route distance in kilometers")
    estimated_time_mins: float = Field(..., description="Estimated travel duration in minutes")
    segments: Optional[List[RouteSegment]] = Field(default=None, description="AQI-colored route segments")
    source_aqi: Optional[float] = Field(default=None, description="AQI at the exact start location")
    source_dominant_pollutant: Optional[str] = Field(default=None, description="Dominant pollutant at source")
    destination_aqi: Optional[float] = Field(default=None, description="AQI at the exact destination location")
    destination_dominant_pollutant: Optional[str] = Field(default=None, description="Dominant pollutant at destination")
    average_route_aqi: Optional[float] = Field(default=None, description="Distance-weighted average AQI along the full route")
    average_aqi: Optional[float] = Field(default=None, description="Alias for average_route_aqi (backward compatibility)")
    maximum_aqi: Optional[float] = Field(default=None, description="Maximum exposure AQI along the route")
    dominant_pollutant: Optional[str] = Field(default=None, description="Dominant pollutant along the route")
    exposure_rating: str = Field(..., description="Exposure safety category (e.g. 'Low', 'Moderate', 'High')")
    resolved_city: Optional[str] = Field(default=None, description="Resolved city name for the route")
    waypoints: Optional[List[str]] = Field(default=None, description="Key waypoints or nodes along the path")
    aqi_data_available: bool = Field(default=True, description="Whether real AQI data was available for this route")
    source_station: Optional[StationMetadata] = Field(default=None, description="Source station metadata")
    destination_station: Optional[StationMetadata] = Field(default=None, description="Destination station metadata")
    confidence: Optional[str] = Field(default=None, description="Prediction confidence score")
    data_quality: Optional[DataQualityMetrics] = Field(default=None, description="Data quality metrics")


class RouteScore(BaseModel):
    """Scoring breakdown for a single route."""
    total_score: float = Field(..., description="Composite optimization score (0-100)")
    aqi_score: float = Field(..., description="AQI exposure score component")
    max_aqi_score: float = Field(..., description="Maximum AQI score component")
    time_score: float = Field(..., description="Travel time score component")
    distance_score: float = Field(..., description="Distance score component")

class RouteTradeOff(BaseModel):
    """Trade-off explanation comparing a route to the recommended route."""
    time_diff_mins: float = Field(..., description="Time difference vs recommended (positive = longer)")
    distance_diff_km: float = Field(..., description="Distance difference vs recommended (positive = longer)")
    aqi_improvement_pct: float = Field(..., description="AQI improvement percentage vs recommended (positive = cleaner)")
    aqi_change: float = Field(..., description="Absolute AQI difference vs recommended")
    is_healthier: bool = Field(..., description="Whether this route is cleaner than the recommended route")
    is_faster: bool = Field(..., description="Whether this route is faster than the recommended route")
    explanation: str = Field(..., description="Human-readable trade-off explanation")

class RouteRecommendation(BaseModel):
    """Recommendation details for the best route."""
    recommended_route_id: str = Field(..., description="ID of the recommended route")
    reasoning: List[str] = Field(..., description="List of reasons explaining the recommendation")
    trade_offs: Optional[List[RouteTradeOff]] = Field(default=None, description="Trade-off comparisons with other routes")
    confidence: str = Field(..., description="Confidence level of the recommendation: 'high', 'medium', 'low'")

class RouteDiagnosticPoint(BaseModel):
    """Diagnostic detail for a single sampled route point."""
    latitude: float
    longitude: float
    aqi_value: Optional[float] = None
    pollutant: Optional[str] = None
    station_name: Optional[str] = None
    station_distance_km: Optional[float] = None
    data_status: str = Field(..., description="'fresh', 'stale', 'fallback', or 'no_data'")

class RouteDiagnostic(BaseModel):
    """Full diagnostic report for a single candidate route."""
    route_id: str = Field(..., description="Unique route identifier")
    sampled_point_count: int = Field(..., description="Number of sampled points analyzed")
    aqi_values: List[Optional[float]] = Field(..., description="AQI at each sampled point")
    sampled_locations: List[RouteDiagnosticPoint] = Field(..., description="Detailed per-point diagnostics")
    stations_used: int = Field(..., description="Number of distinct stations consulted")
    dominant_pollutant: Optional[str] = None
    exposure_score: float = Field(..., description="Computed exposure score")
    recommendation_score: float = Field(..., description="Final weighted recommendation score")
    ranking: int = Field(..., description="Position in the ranking (1 = best)")
    processing_time_ms: float = Field(..., description="Time taken to analyze this route")

class EnhancedRouteOption(RouteOption):
    """Extended route option with optimization metadata."""
    route_id: str = Field(..., description="Unique route identifier (e.g. 'route_A', 'route_B')")
    ranking: int = Field(..., description="Position in the ranking (1 = best)")
    score: Optional[RouteScore] = Field(default=None, description="Scoring breakdown")
    trade_off: Optional[RouteTradeOff] = Field(default=None, description="Trade-off vs recommended route")
    diagnostic: Optional[RouteDiagnostic] = Field(default=None, description="Diagnostic details (when diagnostics enabled)")

class RouteOptimizationResponse(BaseModel):
    """Pydantic response schema returning optimized healthy route suggestions."""
    city: str = Field(..., description="City context")
    routes: List[RouteOption] = Field(..., description="Available optimized routes ranked by exposure and travel time")
    recommended: Optional[RouteRecommendation] = Field(default=None, description="Recommendation details (new V2 engine)")
    candidate_routes: Optional[List[EnhancedRouteOption]] = Field(default=None, description="All candidate routes with scores (new V2 engine)")
    engine_version: str = Field(default="v1", description="Route engine version: 'v1' (analyzer) or 'v2' (optimizer)")


class ExposureAnalyticsRequest(BaseModel):
    """Pydantic request schema (mapped from query parameters) for exposure analytics."""
    city: str = Field(..., min_length=1, description="Target city to analyze exposure analytics for")


class ExposureAnalyticsResponse(BaseModel):
    """Pydantic response schema returning calculated exposure score and safety details."""
    city: str = Field(..., description="Target city name")
    average_aqi: float = Field(..., description="Average AQI calculated over the historical window")
    highest_pollutant: str = Field(..., description="The primary pollutant driver (e.g. 'PM2.5')")
    exposure_score: float = Field(..., description="Calculated exposure index score from 0 (cleanest) to 100 (highest risk)")
    exposure_safety_score: float = Field(..., description="Calculated safety-oriented exposure score from 0 (worst) to 100 (best) for UI gauge")
    health_concern_level: str = Field(..., description="Health category (e.g. 'Satisfactory', 'Poor')")
    suggestions: List[str] = Field(..., description="Personalized guidelines to minimize exposure risk")
    recovery_tips: List[str] = Field(..., description="Actionable recovery tips to minimize exposure risk")
    lungs: str = Field(..., description="Lungs concern and safety risk level")
    heart: str = Field(..., description="Heart concern and safety risk level")
    eyes: str = Field(..., description="Eyes concern and safety risk level")
    exercise: str = Field(..., description="Cardiovascular outdoor exercise recommendation percentage or message")
    outdoor: str = Field(..., description="Maximum recommended outdoor exposure duration")
    mask: str = Field(..., description="Mask type or status recommendation")


class RollingAverageMetadata(BaseModel):
    """Rich diagnostic metadata detailing the rolling average pipeline execution statistics."""
    aggregation_strategy: str = Field(..., description="Aggregation strategy utilized")
    window_hours: int = Field(..., description="Size of the rolling window in hours")
    records_used: int = Field(..., description="Total valid telemetry records incorporated")
    records_discarded: int = Field(..., description="Total corrupted/invalid/outlier records excluded")
    coverage_percent: float = Field(..., description="Temporal coverage percentage within the window")
    rolling_window_start: str = Field(..., description="ISO 8601 timestamp of rolling window start boundary")
    rolling_window_end: str = Field(..., description="ISO 8601 timestamp of rolling window end boundary")
    dominant_pollutant: Optional[str] = Field(None, description="Dominant pollutant identifier")
    confidence: str = Field(..., description="Aggregated confidence rating ('High', 'Medium', 'Low')")
    data_quality: str = Field(..., description="Qualitative telemetry rating ('Excellent', 'Good', 'Fair', 'Poor')")


class CurrentAQIResponse(BaseModel):
    """Pydantic response schema for the latest city AQI representing multi-station aggregate values."""
    city: str = Field(..., description="Name of the city")
    aqi: Optional[float] = Field(None, description="Average AQI calculated across all active stations in the city")
    aqi_category: Optional[str] = Field(None, description="CPCB health category corresponding to the aggregate AQI")
    dominant_pollutant: Optional[str] = Field(None, description="The pollutant with the highest sub-index driving the city AQI (e.g. 'PM2.5')")
    stations_used: int = Field(..., description="Number of active monitoring stations used for the average")
    min_station_aqi: Optional[float] = Field(None, description="Minimum AQI recorded among all active stations in the city")
    max_station_aqi: Optional[float] = Field(None, description="Maximum AQI recorded among all active stations in the city")
    recorded_at: datetime = Field(..., description="The most recent update time among all reporting stations")
    data_age_hours: Optional[float] = Field(default=None, description="Age of the most recent data in hours since measurement")
    freshness_status: Optional[str] = Field(default=None, description="Data freshness rating ('fresh', 'acceptable', 'stale')")
    source: str = Field("OpenAQ", description="The data source provider")
    fallback_used: bool = Field(default=False, description="Indicates if fallback data source was utilized")
    cpcb_methodology: str = Field(..., description="CPCB methodology utilized ('rolling_average' or 'instantaneous_estimate')")
    confidence: str = Field(..., description="Scientific confidence rating ('high', 'medium', 'low')")
    metadata: Optional[RollingAverageMetadata] = Field(default=None, description="Detailed 24-hour rolling average aggregation metadata")

    # Pollutants (optional breakdown)
    pm25: Optional[float] = Field(default=None, description="PM2.5 concentration in ug/m3")
    pm10: Optional[float] = Field(default=None, description="PM10 concentration in ug/m3")
    no2: Optional[float] = Field(default=None, description="NO2 concentration in ug/m3")
    so2: Optional[float] = Field(default=None, description="SO2 concentration in ug/m3")
    o3: Optional[float] = Field(default=None, description="O3 concentration in ug/m3")
    co: Optional[float] = Field(default=None, description="CO concentration in mg/m3")

    # Weather (optional conditions)
    temperature: Optional[float] = Field(default=None, description="Temperature in Celsius")
    humidity: Optional[float] = Field(default=None, description="Relative humidity percentage")
    wind_speed: Optional[float] = Field(default=None, description="Wind speed in km/h")
    wind_direction: Optional[float] = Field(default=None, description="Wind direction in degrees")
    pressure: Optional[float] = Field(default=None, description="Surface pressure in hPa")

    # Location (optional coordinates)
    latitude: Optional[float] = Field(default=None, description="Resolved latitude of the city")
    longitude: Optional[float] = Field(default=None, description="Resolved longitude of the city")

    model_config = {
        "from_attributes": True
    }


class WeatherResponse(BaseModel):
    """Pydantic response schema representing current weather conditions.

    All meteorological values originate from authoritative data sources:
    - Open-Meteo for atmospheric measurements
    - Nominatim for geographic metadata
    """

    # ── Location ─────────────────────────────────────────────────────────
    city: str = Field(..., description="Target city name")
    country: Optional[str] = Field(default=None, description="Full country name (e.g. 'India')")
    country_code: Optional[str] = Field(default=None, description="ISO 3166-1 alpha-2 code (e.g. 'IN')")
    latitude: float = Field(..., description="Resolved latitude")
    longitude: float = Field(..., description="Resolved longitude")
    timezone: Optional[str] = Field(default=None, description="IANA timezone (e.g. 'Asia/Kolkata')")

    # ── Core Meteorological ──────────────────────────────────────────────
    temperature: Optional[float] = Field(default=None, description="Temperature in Celsius")
    feels_like: Optional[float] = Field(default=None, description="Apparent temperature in Celsius (from Open-Meteo)")
    humidity: Optional[float] = Field(default=None, description="Relative humidity percentage")
    wind_speed: Optional[float] = Field(default=None, description="Wind speed in km/h")
    wind_speed_unit: str = Field(default="km/h", description="Wind speed unit")
    wind_direction: Optional[float] = Field(default=None, description="Wind direction in degrees (0-360)")
    pressure: Optional[float] = Field(default=None, description="Surface pressure in hPa")
    precipitation: Optional[float] = Field(default=None, description="Precipitation in mm")

    # ── Weather Condition ────────────────────────────────────────────────
    weather_code: Optional[int] = Field(default=None, description="WMO weather interpretation code")
    condition: Optional[str] = Field(default=None, description="Condition category (e.g. 'Clear', 'Rain', 'Clouds')")
    condition_description: Optional[str] = Field(default=None, description="Human-readable description (e.g. 'clear sky')")
    condition_icon: Optional[str] = Field(default=None, description="OpenWeatherMap-compatible icon code (e.g. '01d')")

    # ── Solar ────────────────────────────────────────────────────────────
    sunrise: Optional[str] = Field(default=None, description="Sunrise in ISO 8601 format")
    sunset: Optional[str] = Field(default=None, description="Sunset in ISO 8601 format")
    sunrise_timestamp: Optional[int] = Field(default=None, description="Sunrise as Unix timestamp (seconds)")
    sunset_timestamp: Optional[int] = Field(default=None, description="Sunset as Unix timestamp (seconds)")

    # ── Provider Metadata ────────────────────────────────────────────────
    provider: str = Field(default="Open-Meteo", description="Weather data provider")

    # ── Raw (for debugging / advanced consumers) ─────────────────────────
    raw_response: dict = Field(default_factory=dict, description="Raw JSON response from Open-Meteo Weather API")


