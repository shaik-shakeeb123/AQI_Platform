import asyncio
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from fastapi import HTTPException
from api_layer.logging import get_logger
from api_layer.api.schemas.aqi_endpoints import SafeWindowRequest, SafeWindowResponse
from api_layer.repositories.prediction_repository import PredictionRepository
from database.models.aqi_data import AQIData

from services.weather_service import WeatherService
from services.recommendation import get_safe_window_recommendations
from services.aqi_category import get_us_aqi_category
from ml_training.inference.predictor import MLPredictorService

logger = get_logger(__name__)

class SafeWindowService:
    """Service simulating future AQI trends to compute outdoor safe window blocks."""

    def __init__(self, repository: Optional[PredictionRepository] = None) -> None:
        self.repository = repository

    async def get_safe_window(
        self_or_city: Any = None,
        records_or_payload: Any = None,
        lat_or_default_model: Any = None,
        lon_or_models: Any = None,
        model: Any = None,
        models: Optional[Dict[str, Any]] = None,
        city: Optional[str] = None,
        records: Optional[List[Any]] = None,
        lat: Optional[float] = None,
        lon: Optional[float] = None,
        payload: Optional[Any] = None,
        default_model: Optional[Any] = None,
    ) -> Any:
        # Determine if called as an instance method (Controller path) or class static method (Legacy test path)
        if isinstance(self_or_city, SafeWindowService):
            # Controller Path
            actual_payload = payload if payload is not None else records_or_payload
            actual_default_model = default_model if default_model is not None else lat_or_default_model
            actual_models = models if models is not None else lon_or_models
            
            return await self_or_city._get_safe_window_orchestrated(actual_payload, actual_default_model, actual_models)
        else:
            # Legacy Test Path
            actual_city = city if city is not None else self_or_city
            actual_records = records if records is not None else records_or_payload
            actual_lat = lat if lat is not None else lat_or_default_model
            actual_lon = lon if lon is not None else lon_or_models
            actual_model = model
            actual_models = models
            
            return await SafeWindowService._run_simulation(
                actual_city, actual_records, actual_lat, actual_lon, actual_model, actual_models
            )

    async def _get_safe_window_orchestrated(
        self,
        payload: SafeWindowRequest,
        default_model: Any,
        models: Dict[str, Any]
    ) -> SafeWindowResponse:
        """Fetch records from repository/API fallback and simulate safest window."""
        logger.info(f"Querying safe window for city={payload.city}")
        
        if not self.repository:
            raise RuntimeError("SafeWindowService repository is not configured.")
            
        records = await asyncio.to_thread(
            self.repository.get_recent_history_for_city, payload.city, 24
        )
        
        if not records:
            # Fallback Strategy: Geocode using Nominatim, fetch current air quality and weather from Open-Meteo
            logger.info(f"No database records found for city '{payload.city}'. Invoking fallback to resolve safe window.")
            from data_sync.clients.nominatim_client import NominatimGeocoderClient
            from data_sync.clients.openmeteo_air_quality_client import OpenMeteoAirQualityClient
            from services.dominant_pollutant import calculate_overall_aqi
            
            coords = await NominatimGeocoderClient.geocode_address(payload.city, "")
            if not coords:
                raise HTTPException(
                    status_code=404,
                    detail=f"No safe window could be calculated: geocoding failed for fallback city '{payload.city}'."
                )
            lat, lon = coords
            
            try:
                client = OpenMeteoAirQualityClient()
                aq_data = await client.fetch_air_quality(lat, lon)
            except Exception as e:
                raise HTTPException(
                    status_code=404,
                    detail=f"No safe window could be calculated: fallback Open-Meteo query failed for '{payload.city}'."
                )
                
            if not aq_data or "current" not in aq_data:
                raise HTTPException(
                    status_code=404,
                    detail=f"No safe window could be calculated: Open-Meteo response was empty for '{payload.city}'."
                )
                
            current = aq_data["current"]
            pm25 = current.get("pm2_5") or 15.0
            pm10 = current.get("pm10") or 30.0
            no2 = current.get("nitrogen_dioxide") or 10.0
            so2 = current.get("sulphur_dioxide") or 5.0
            o3 = current.get("ozone") or 20.0
            raw_co = current.get("carbon_monoxide") or 200.0
            co = raw_co / 1000.0
            
            calc_res = calculate_overall_aqi(pm25=pm25, pm10=pm10, no2=no2, so2=so2, co=co, o3=o3)
            current_aqi, category, _ = calc_res
            if current_aqi is None:
                current_aqi = 50.0
                
            # Construct 24 hours of sequential mock telemetry to feed the ML model
            now = datetime.utcnow()
            fallback_records = []
            for h in range(24):
                rec = AQIData(
                    city=payload.city,
                    recorded_at=now - timedelta(hours=24 - h),
                    latitude=lat,
                    longitude=lon,
                    pm25=pm25,
                    pm10=pm10,
                    no2=no2,
                    so2=so2,
                    co=co * 1000.0,  # DB stores CO in ug/m3
                    o3=o3,
                    aqi=current_aqi,
                    aqi_category=category,
                    temperature=25.0,
                    humidity=60.0,
                    wind_speed=5.0,
                    wind_direction=180.0,
                    precipitation=0.0,
                    pressure=1013.0
                )
                fallback_records.append(rec)
                
            records = fallback_records
            
        # Extract coordinates from the latest database record
        latest_db_record = records[0]
        lat = latest_db_record.latitude
        lon = latest_db_record.longitude
        
        # Try geocoding fallback if coordinates are missing
        if lat is None or lon is None:
            logger.info(f"Coordinates missing from latest DB record for city {payload.city}. Falling back to geocoding.")
            try:
                from services.route_optimizer import RouteOptimizerService
                coords = await RouteOptimizerService.geocode_address(payload.city, payload.city)
                if coords:
                    lat, lon = coords
                    logger.info(f"Geocoding resolved coordinates for {payload.city}: ({lat}, {lon})")
            except Exception as ge_err:
                logger.error(f"Geocoding fallback failed for city {payload.city}: {ge_err}")
                
        try:
            result = await SafeWindowService._run_simulation(
                payload.city, records, lat, lon, default_model, models
            )
            return SafeWindowResponse(
                city=latest_db_record.city or payload.city,
                **result
            )
        except Exception as e:
            logger.error(f"Safe window computation failed: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Safe window execution failed: {str(e)}"
            )

    @staticmethod
    async def _run_simulation(
        city: str,
        records: List[Any],
        lat: Optional[float],
        lon: Optional[float],
        model: Any,
        models: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Runs simulation forecast to identify safest 2-hour outdoor hours block."""
        # Try fetching hourly weather forecast if coords are valid
        forecast_map = {}
        if lat is not None and lon is not None:
            forecast_map = await WeatherService.fetch_hourly_forecast(lat, lon)

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
                "cloud_cover": None,
                "timestamp": r.recorded_at.isoformat() if r.recorded_at else None
            })
            
        history_dicts = sorted(history_payload, key=lambda x: x["timestamp"])
        latest_record = history_dicts[-1]
        
        latest_time_str = latest_record["timestamp"]
        if isinstance(latest_time_str, str):
            latest_time = datetime.fromisoformat(latest_time_str.replace("Z", "+00:00")).replace(tzinfo=None)
        else:
            latest_time = latest_time_str
            
        forecast_timeline = []
        for hour_offset in range(1, 25):
            future_time = latest_time + timedelta(hours=hour_offset)
            future_record = latest_record.copy()
            future_record["timestamp"] = future_time
            
            forecast_key = (future_time.year, future_time.month, future_time.day, future_time.hour)
            if forecast_key in forecast_map:
                f_val = forecast_map[forecast_key]
                if f_val["temperature"] is not None:
                    future_record["temperature"] = f_val["temperature"]
                if f_val["humidity"] is not None:
                    future_record["humidity"] = f_val["humidity"]
                if f_val["wind_speed"] is not None:
                    future_record["wind_speed"] = f_val["wind_speed"]
                if f_val["wind_direction"] is not None:
                    future_record["wind_direction"] = f_val["wind_direction"]
                if f_val["precipitation"] is not None:
                    future_record["precipitation"] = f_val["precipitation"]
                if f_val["pressure"] is not None:
                    future_record["pressure"] = f_val["pressure"]
                if f_val["cloud_cover"] is not None:
                    future_record["cloud_cover"] = f_val["cloud_cover"]
                    
            temp_history = history_dicts + [future_record]
            
            # Select appropriate model based on target hour offset
            chosen_model = model
            if models:
                if hour_offset == 1:
                    chosen_model = models.get("1h") or model
                elif hour_offset <= 3:
                    chosen_model = models.get("3h") or model
                elif hour_offset <= 6:
                    chosen_model = models.get("6h") or model
                elif hour_offset <= 12:
                    chosen_model = models.get("12h") or model
                else:
                    chosen_model = models.get("24h") or model
            
            future_aqi = MLPredictorService.predict_aqi(chosen_model, temp_history)
            
            forecast_timeline.append({
                "timestamp": future_time,
                "predicted_aqi": future_aqi
            })
            
        duration = 2
        best_avg_aqi = float("inf")
        best_window_index = 0
        
        for i in range(len(forecast_timeline) - duration + 1):
            window_segment = forecast_timeline[i : i + duration]
            avg_aqi = sum(item["predicted_aqi"] for item in window_segment) / duration
            if avg_aqi < best_avg_aqi:
                best_avg_aqi = avg_aqi
                best_window_index = i
                
        selected_window = forecast_timeline[best_window_index : best_window_index + duration]
        start_time = selected_window[0]["timestamp"]
        end_time = selected_window[-1]["timestamp"] + timedelta(hours=1)
        
        category = get_us_aqi_category(best_avg_aqi)
        recommendations = get_safe_window_recommendations(category)
        
        humidity = latest_record.get("humidity") or 50.0
        temperature = latest_record.get("temperature") or 25.0
        if humidity > 80.0:
            weather_condition = "Humid"
        elif humidity > 65.0:
            weather_condition = "Partly Cloudy"
        elif temperature > 35.0:
            weather_condition = "Sunny"
        else:
            weather_condition = "Clear"
            
        return {
            "safe_window_start": start_time.isoformat(),
            "safe_window_end": end_time.isoformat(),
            "duration_hours": duration,
            "predicted_aqi": round(best_avg_aqi, 2),
            "safety_level": category,
            "weather_condition": weather_condition,
            "recommendations": recommendations
        }
