from datetime import datetime
from typing import Any, Dict
from fastapi import HTTPException
from api_layer.logging import get_logger
from api_layer.api.schemas.aqi_endpoints import PredictAQIRequest, PredictAQIResponse
from api_layer.repositories.prediction_repository import PredictionRepository
from services.aqi_category import get_us_aqi_category
from ml_training.inference.predictor import MLPredictorService

logger = get_logger(__name__)

class PredictionService:
    """Application service orchestrating AQI forecasting workflow use cases.
    
    Acts as a bridge between the presentation controller and the core ML domain inference layer.
    """

    def __init__(self, repository: PredictionRepository) -> None:
        self.repository = repository

    def predict_aqi(self, payload: PredictAQIRequest, default_model: Any, models: Dict[str, Any]) -> PredictAQIResponse:
        """Fetch history, prepare feature inputs, delegate prediction to ML domain, and compile the API response."""
        logger.info(f"Retrieving historical measurements from repository for city={payload.city}")
        
        # 1. Retrieve the required historical data from persistence layer
        records = self.repository.get_recent_history_for_city(payload.city, limit=24)
        
        # 2. Business validation / handle insufficient records
        if not records:
            logger.info(f"Insufficient database logs found for city '{payload.city}' to execute ML forecast.")
            return PredictAQIResponse(
                predicted_aqi=None,
                category=None,
                predicted_at=datetime.utcnow(),
                prediction_source="insufficient-data",
                message="Prediction unavailable: sufficient historical data (minimum 24 hours of sequential telemetry) is not available in the database to execute the machine learning model forecast."
            )
            
        # 3. Prepare the prediction history payload
        history_payload = []
        for r in reversed(records):
            history_payload.append({
                "pm25": r.pm25,
                "pm10": r.pm10,
                "no2": r.no2,
                "o3": r.o3,
                "co": r.co,
                "so2": r.so2,
                "temperature": r.temperature,
                "humidity": r.humidity,
                "wind_speed": r.wind_speed,
                "wind_direction": r.wind_direction,
                "precipitation": r.precipitation,
                "pressure": r.pressure,
                "timestamp": r.recorded_at.isoformat() if r.recorded_at else None
            })
            
        # Apply payload overrides from request
        if history_payload:
            latest = history_payload[-1]
            if payload.pm25 is not None:
                latest["pm25"] = payload.pm25
            if payload.pm10 is not None:
                latest["pm10"] = payload.pm10
            if payload.no2 is not None:
                latest["no2"] = payload.no2
            if payload.o3 is not None:
                latest["o3"] = payload.o3
            if payload.co is not None:
                latest["co"] = payload.co
            if payload.so2 is not None:
                latest["so2"] = payload.so2
            if payload.temperature is not None:
                latest["temperature"] = payload.temperature
            if payload.humidity is not None:
                latest["humidity"] = payload.humidity

        # 4. Resolve the ML model for the requested horizon
        horizon = payload.horizon or "1h"
        model = models.get(horizon, None)
        if model is None:
            model = default_model
            
        # 5. Call MLPredictorService (Domain Layer) and handle errors
        try:
            predicted_val = MLPredictorService.predict_aqi(model, history_payload)
            category = get_us_aqi_category(predicted_val)
            
            # 6. Convert predicted values to the API Response model
            return PredictAQIResponse(
                predicted_aqi=round(predicted_val, 2),
                category=category,
                predicted_at=datetime.utcnow(),
                prediction_source="ml-model"
            )
        except Exception as e:
            logger.error(f"Inference execution failed: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Inference execution failed: {str(e)}"
            )
