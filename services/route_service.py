from fastapi import HTTPException
from api_layer.logging import get_logger
from api_layer.api.schemas.aqi_endpoints import (
    RouteOptimizationRequest,
    RouteOptimizationResponse,
    RouteOption,
    RouteSegment,
)
from services.route_optimizer import RouteOptimizerService
from sqlalchemy.orm import Session

logger = get_logger(__name__)


def _build_route_option(route_data: dict, start_point: str, destination: str) -> RouteOption:
    """Build a V1-compatible RouteOption from route data dict."""
    avg_aqi = route_data.get("average_route_aqi")
    exp_rating = route_data.get("exposure_rating", "Low")
    return RouteOption(
        route_name=route_data.get("route_name", "Optimal Route"),
        distance_km=route_data.get("distance_km"),
        estimated_time_mins=route_data.get("estimated_time_mins"),
        segments=[RouteSegment(**seg) for seg in route_data.get("segments", [])] if route_data.get("segments") else None,
        source_aqi=route_data.get("source_aqi"),
        source_dominant_pollutant=route_data.get("source_dominant_pollutant"),
        destination_aqi=route_data.get("destination_aqi"),
        destination_dominant_pollutant=route_data.get("destination_dominant_pollutant"),
        average_route_aqi=avg_aqi,
        average_aqi=avg_aqi,
        maximum_aqi=route_data.get("maximum_aqi"),
        dominant_pollutant=route_data.get("dominant_pollutant"),
        exposure_rating=exp_rating,
        resolved_city=route_data.get("resolved_city"),
        waypoints=[start_point, destination],
        aqi_data_available=route_data.get("aqi_data_available", False),
        source_station=route_data.get("source_station"),
        destination_station=route_data.get("destination_station"),
        confidence=route_data.get("confidence"),
        data_quality=route_data.get("data_quality"),
    )


class RouteService:
    """Service orchestrating healthy AQI exposure route optimization."""

    def __init__(self) -> None:
        pass

    async def get_route(self, db: Session, payload: RouteOptimizationRequest) -> RouteOptimizationResponse:
        """Call route optimization engine and map/format optimized route suggestions."""
        logger.info(f"Querying optimized route. City context: {payload.city}")

        route_data = await RouteOptimizerService.get_optimized_exposure_route(
            city=payload.city,
            start_point=payload.start_point,
            destination=payload.destination,
            db=db,
        )

        if not route_data:
            raise HTTPException(
                status_code=502,
                detail="External OSRM or Nominatim routing/geocoding service failed."
            )

        db_city = route_data.get("resolved_city") or payload.city or "Unknown Location"
        route_option = _build_route_option(route_data, payload.start_point, payload.destination)

        return RouteOptimizationResponse(
            city=db_city,
            routes=[route_option],
            recommended=None,
            candidate_routes=None,
            engine_version="v1",
        )
