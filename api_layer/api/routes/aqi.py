"""FastAPI endpoints for air quality measurements, history, and insights.

Acts as a thin controller layer delegating execution to decoupled services.
"""

from typing import List, Optional, Any
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from database.connection import get_db
from api_layer.api.schemas.aqi_endpoints import (
    AQIMeasurementResponse,
    PredictAQIRequest,
    PredictAQIResponse,
    HealthInsightsResponse,
    SafeWindowRequest,
    SafeWindowResponse,
    RouteOptimizationRequest,
    RouteOptimizationResponse,
    ExposureAnalyticsResponse,
    CurrentAQIResponse,
    WeatherResponse
)

# Import Repositories
from api_layer.repositories.history_repository import HistoryRepository
from api_layer.repositories.prediction_repository import PredictionRepository
from api_layer.repositories.current_aqi_repository import CurrentAQIRepository
from api_layer.repositories.exposure_repository import ExposureRepository
from api_layer.repositories.diagnostics_repository import DiagnosticsRepository

# Import Services
from services.history_service import HistoryService
from services.prediction_service import PredictionService
from services.current_aqi_service import CurrentAQIService
from services.health_service import HealthService
from services.safe_window_service import SafeWindowService
from services.route_service import RouteService
from services.exposure_service import ExposureService
from services.weather_service import WeatherService
from services.diagnostics_service import DiagnosticsService

router = APIRouter()


@router.get("/history", response_model=List[AQIMeasurementResponse], tags=["Air Quality Intelligence"])
def get_history(
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(100, ge=1, le=500, description="Maximum number of records to return"),
    city: Optional[str] = Query(None, description="Filter by city name (case-insensitive)"),
    sort: str = Query("desc", description="Sort order by recorded time ('asc' or 'desc')"),
    db: Session = Depends(get_db),
) -> List[AQIMeasurementResponse]:
    """Retrieve historical air quality metrics sorted by recorded time."""
    repo = HistoryRepository(db)
    service = HistoryService(repo)
    return service.get_history(skip, limit, city, sort)


@router.post("/predictAQI", response_model=PredictAQIResponse, tags=["Air Quality Intelligence"])
def predict_aqi(
    payload: PredictAQIRequest,
    request: Request,
    db: Session = Depends(get_db)
) -> PredictAQIResponse:
    """Predict future AQI based on 24-hour historical trends for a city by running ML inference directly."""
    repo = PredictionRepository(db)
    service = PredictionService(repo)
    default_model = getattr(request.app.state, "model", None)
    models = getattr(request.app.state, "models", {})
    return service.predict_aqi(payload, default_model, models)


@router.get("/getHealthInsights", response_model=HealthInsightsResponse, tags=["Air Quality Intelligence"])
async def get_health_insights(
    city: str = Query(..., min_length=1, description="Target city for health insights"),
    db: Session = Depends(get_db),
) -> HealthInsightsResponse:
    """Provide health insights and recommendations by analyzing telemetry locally."""
    repo = PredictionRepository(db)
    service = HealthService(repo)
    return await service.get_health_insights(city)


@router.post("/getSafeWindow", response_model=SafeWindowResponse, tags=["Air Quality Intelligence"])
async def get_safe_window(
    payload: SafeWindowRequest,
    request: Request,
    db: Session = Depends(get_db)
) -> SafeWindowResponse:
    """Identify the safest outdoor window for a city by simulating future AQI trends."""
    repo = PredictionRepository(db)
    service = SafeWindowService(repo)
    default_model = getattr(request.app.state, "model", None)
    models = getattr(request.app.state, "models", {})
    return await service.get_safe_window(payload, default_model, models)


@router.post("/getRoute", response_model=RouteOptimizationResponse, tags=["Air Quality Intelligence"])
async def get_route(
    payload: RouteOptimizationRequest,
    db: Session = Depends(get_db)
) -> RouteOptimizationResponse:
    """Identify optimized healthy route suggestions by running geocoding and routing checks locally."""
    service = RouteService()
    return await service.get_route(db, payload)


@router.get("/exposure", response_model=ExposureAnalyticsResponse, tags=["Air Quality Intelligence"])
async def get_exposure_analytics(
    city: str = Query(..., min_length=1, description="Target city to analyze exposure analytics for"),
    db: Session = Depends(get_db)
) -> ExposureAnalyticsResponse:
    """Analyze exposure score and safety details for a city by processing trends locally."""
    repo = ExposureRepository(db)
    service = ExposureService(repo)
    return await service.get_exposure_analytics(city)


@router.get("/currentAQI", response_model=CurrentAQIResponse, tags=["Air Quality Intelligence"])
async def get_current_aqi(
    city: str = Query(..., min_length=1, description="Target city to retrieve latest AQI for"),
    diagnose: bool = Query(False, description="Expose the complete calculation pipeline for diagnosis"),
    db: Session = Depends(get_db)
) -> Any:
    """Retrieve the aggregate current AQI for a city computed across all active stations in the last 24 hours."""
    repo = CurrentAQIRepository(db)
    service = CurrentAQIService(repo)
    if diagnose:
        diag_data = await service.get_current_aqi_diagnostics(city)
        return JSONResponse(content=diag_data)
    return await service.get_current_aqi(city)


@router.get("/weather", response_model=WeatherResponse, tags=["Weather"])
async def get_weather(
    city: str = Query(..., min_length=1, description="Target city to retrieve current weather for")
) -> WeatherResponse:
    """Retrieve the current weather conditions for a city."""
    service = WeatherService()
    return await service.get_weather(city)


@router.get("/diagnostics", tags=["System Diagnostics"])
async def get_diagnostics(
    request: Request,
    db: Session = Depends(get_db)
) -> dict:
    """Run system diagnostics to check database, scheduler, and loaded ML models."""
    repo = DiagnosticsRepository(db)
    service = DiagnosticsService(repo)
    app_state_models = getattr(request.app.state, "models", {})
    app_state_model = getattr(request.app.state, "model", None)
    return await service.get_diagnostics(app_state_models, app_state_model)
