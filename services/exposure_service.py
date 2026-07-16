import asyncio
from fastapi import HTTPException
from api_layer.logging import get_logger
from api_layer.api.schemas.aqi_endpoints import ExposureAnalyticsResponse
from api_layer.repositories.exposure_repository import ExposureRepository
from services.aqi_category import get_aqi_category
from services.recommendation import get_exposure_suggestions

logger = get_logger(__name__)

class ExposureService:
    """Service orchestrating business analytics for localized user exposure levels."""

    def __init__(self, repository: ExposureRepository) -> None:
        self.repository = repository

    async def get_exposure_analytics(self, city: str) -> ExposureAnalyticsResponse:
        """Fetch historical records, compute rolling average AQI, score exposure levels, and suggest advice."""
        logger.info(f"Querying exposure analytics for city={city}")
        
        records = await asyncio.to_thread(
            self.repository.get_recent_history_for_city, city, 24
        )
        
        if not records:
            # Fallback strategy: Geocode the city and query Open-Meteo Air Quality
            logger.info(f"No database history found for '{city}'. Invoking Open-Meteo fallback for exposure analytics...")
            from data_sync.clients.nominatim_client import NominatimGeocoderClient
            from data_sync.clients.openmeteo_air_quality_client import OpenMeteoAirQualityClient
            
            coords = await NominatimGeocoderClient.geocode_address(city, "")
            if not coords:
                logger.warning(f"Geocoding failed for exposure fallback of city={city}")
                raise HTTPException(
                    status_code=404,
                    detail=f"No historical records found for city '{city}' to run exposure analysis, and geocoding failed."
                )
            
            lat, lon = coords
            try:
                client = OpenMeteoAirQualityClient()
                aq_data = await client.fetch_air_quality(lat, lon)
                if aq_data and "current" in aq_data:
                    current = aq_data["current"]
                    pm25 = current.get("pm2_5", 35.0)
                    pm10 = current.get("pm10", 65.0)
                    no2 = current.get("nitrogen_dioxide", 20.0)
                    so2 = current.get("sulphur_dioxide", 5.0)
                    o3 = current.get("ozone", 30.0)
                    raw_co = current.get("carbon_monoxide")
                    co = raw_co / 1000.0 if raw_co is not None else 0.5
                    
                    from services.dominant_pollutant import calculate_overall_aqi
                    avg_aqi, _, _ = calculate_overall_aqi(pm25=pm25, pm10=pm10, no2=no2, so2=so2, co=co, o3=o3)
                    if avg_aqi is None:
                        avg_aqi = 50.0
                    
                    db_city = city
                    highest_pollutant = "PM2.5"
                else:
                    raise Exception("Empty Open-Meteo response")
            except Exception as e:
                logger.error(f"Open-Meteo fallback failed for exposure analytics of city={city}: {e}")
                raise HTTPException(
                    status_code=502,
                    detail=f"Failed to fetch fallback exposure analytics for city '{city}': {str(e)}"
                )
        else:
            aqis = [r.aqi for r in records if r.aqi is not None]
            avg_aqi = sum(aqis) / len(aqis) if aqis else 50.0
            db_city = records[0].city if records[0].city else city
            
            # Find dominant/highest pollutant
            pollutants = ["pm25", "pm10", "no2", "o3", "co", "so2"]
            highest_pollutant = "PM2.5"
            max_val = 0.0
            latest_rec = records[0]
            for p in pollutants:
                val = getattr(latest_rec, p, None)
                if val is not None and val > max_val:
                    max_val = val
                    highest_pollutant = p.upper().replace("PM25", "PM2.5").replace("PM10", "PM10")
                
        # 1. Legacy exposure risk score (retained for backward compatibility and test stability)
        exposure_score = min(max(round((avg_aqi / 300.0) * 100.0, 2), 0.0), 100.0)

        # 2. New safety score calculated on the backend to drive the presentation-only UI gauge
        if avg_aqi <= 50:
            exposure_safety_score = 95.0
            lungs = "Excellent"
            heart = "Excellent"
            eyes = "No Risk"
            exercise = "100%"
            outdoor = "Unlimited"
            mask = "Not Required"
            tips = [
                "Drink enough water",
                "Enjoy outdoor activities",
                "Keep monitoring AQI"
            ]
        elif avg_aqi <= 100:
            exposure_safety_score = 85.0
            lungs = "Low Risk"
            heart = "Low Risk"
            eyes = "Mild Irritation"
            exercise = "90%"
            outdoor = "4 Hours"
            mask = "Optional"
            tips = [
                "Prefer parks and green areas",
                "Carry water bottle",
                "Reduce exposure near traffic"
            ]
        elif avg_aqi <= 150:
            exposure_safety_score = 72.0
            lungs = "Moderate Risk"
            heart = "Low Risk"
            eyes = "Irritation Possible"
            exercise = "80%"
            outdoor = "2 Hours"
            mask = "Recommended"
            tips = [
                "Use N95 mask",
                "Drink warm water",
                "Wash face after coming home",
                "Limit prolonged outdoor activities"
            ]
        elif avg_aqi <= 200:
            exposure_safety_score = 50.0
            lungs = "High Risk"
            heart = "Moderate Risk"
            eyes = "High Irritation"
            exercise = "60%"
            outdoor = "1 Hour"
            mask = "Required"
            tips = [
                "Stay indoors",
                "Use air purifier",
                "Avoid outdoor exercise",
                "Monitor breathing difficulties"
            ]
        else:
            exposure_safety_score = 30.0
            lungs = "Very High Risk"
            heart = "High Risk"
            eyes = "Severe Irritation"
            exercise = "40%"
            outdoor = "30 Minutes"
            mask = "Mandatory"
            tips = [
                "Avoid outdoor exposure",
                "Keep windows closed",
                "Use air purifier",
                "Seek medical help if symptoms worsen"
            ]

        health_concern_level = get_aqi_category(avg_aqi)
        suggestions = get_exposure_suggestions(health_concern_level)
            
        return ExposureAnalyticsResponse(
            city=db_city,
            average_aqi=round(avg_aqi, 2),
            highest_pollutant=highest_pollutant,
            exposure_score=exposure_score,
            exposure_safety_score=exposure_safety_score,
            health_concern_level=health_concern_level,
            suggestions=suggestions,
            recovery_tips=tips,
            lungs=lungs,
            heart=heart,
            eyes=eyes,
            exercise=exercise,
            outdoor=outdoor,
            mask=mask
        )
