import asyncio
from fastapi import HTTPException
from api_layer.logging import get_logger
from api_layer.api.schemas.aqi_endpoints import HealthInsightsResponse
from api_layer.repositories.prediction_repository import PredictionRepository
from services.aqi_category import get_aqi_category
from services.recommendation import get_health_insights_recommendations

logger = get_logger(__name__)

class HealthService:
    """Service orchestrating health recommendations and warnings based on AQI levels."""

    def __init__(self, repository: PredictionRepository) -> None:
        self.repository = repository

    async def get_health_insights(self, city: str) -> HealthInsightsResponse:
        """Fetch current AQI from database or Open-Meteo fallback, and compile health recommendations."""
        logger.info(f"Retrieving health insights for city={city}")
        
        records = await asyncio.to_thread(
            self.repository.get_recent_history_for_city, city, 24
        )
        
        if records:
            # Determine current AQI from the latest database record
            latest_rec = records[0]
            current_aqi = latest_rec.aqi if latest_rec.aqi is not None else 50.0
            db_city = latest_rec.city if latest_rec.city else city
            
            status = get_aqi_category(current_aqi)
            risk_level, recommendations, safety_warnings = get_health_insights_recommendations(status)
                
            return HealthInsightsResponse(
                city=db_city,
                current_aqi=round(current_aqi, 2),
                status=status,
                risk_level=risk_level,
                recommendations=recommendations,
                safety_warnings=safety_warnings,
                source="database"
            )

        # --- FALLBACK STRATEGY (Open-Meteo Air Quality API) ---
        logger.info(f"No database records found for city={city}. Invoking Open-Meteo fallback for health insights...")
        
        from data_sync.clients.nominatim_client import NominatimGeocoderClient
        from data_sync.clients.openmeteo_air_quality_client import OpenMeteoAirQualityClient
        from services.dominant_pollutant import calculate_overall_aqi
        
        coords = await NominatimGeocoderClient.geocode_address(city, "")
        if not coords:
            logger.warning(f"Geocoding failed for health insights fallback of city={city}")
            raise HTTPException(
                status_code=404,
                detail=f"No health insights found for city '{city}', and location geocoding failed."
            )
            
        lat, lon = coords
        try:
            client = OpenMeteoAirQualityClient()
            aq_data = await client.fetch_air_quality(lat, lon)
        except Exception as e:
            logger.error(f"Open-Meteo Air Quality fallback failed for health insights: {e}")
            raise HTTPException(
                status_code=404,
                detail=f"No health insights found for city '{city}' and fallback Open-Meteo query failed."
            )
            
        if not aq_data or "current" not in aq_data:
            raise HTTPException(
                status_code=404,
                detail=f"No health insights found for city '{city}' and fallback Open-Meteo response was empty."
            )
            
        current = aq_data["current"]
        pm25 = current.get("pm2_5")
        pm10 = current.get("pm10")
        no2 = current.get("nitrogen_dioxide")
        so2 = current.get("sulphur_dioxide")
        o3 = current.get("ozone")
        raw_co = current.get("carbon_monoxide")
        co = raw_co / 1000.0 if raw_co is not None else None
        
        calc_res = calculate_overall_aqi(pm25=pm25, pm10=pm10, no2=no2, so2=so2, co=co, o3=o3)
        current_aqi, category, _ = calc_res
        
        if current_aqi is None:
            current_aqi = 50.0
            category = "Good"
            
        status = category or get_aqi_category(current_aqi)
        risk_level, recommendations, safety_warnings = get_health_insights_recommendations(status)
        
        return HealthInsightsResponse(
            city=city,
            current_aqi=round(current_aqi, 2),
            status=status,
            risk_level=risk_level,
            recommendations=recommendations,
            safety_warnings=safety_warnings,
            source="open-meteo-fallback"
        )
