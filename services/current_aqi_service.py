from __future__ import annotations
import asyncio
import time
import math
from datetime import datetime, timedelta, timezone
from fastapi import HTTPException
from api_layer.logging import get_logger
from api_layer.config import get_settings
from api_layer.api.schemas.aqi_endpoints import CurrentAQIResponse, RollingAverageMetadata
from api_layer.repositories.current_aqi_repository import CurrentAQIRepository
from services.aqi_category import get_aqi_category
from services.dominant_pollutant import calculate_overall_aqi
from data_sync.clients.nominatim_client import NominatimGeocoderClient
from data_sync.clients.openmeteo_air_quality_client import OpenMeteoAirQualityClient
from data_sync.clients.openmeteo_weather_client import OpenMeteoWeatherClient
from data_sync.data_processor import DataProcessor

logger = get_logger(__name__)


def compute_nowcast(records: list, pollutant: str, now: datetime) -> dict:
    """Compute US EPA NowCast concentration and diagnostics for a pollutant."""
    # 1. Deduplicate by timestamp
    seen_timestamps = set()
    dedup = []
    for r in records:
        ts = r.recorded_at
        if ts not in seen_timestamps:
            seen_timestamps.add(ts)
            dedup.append(r)

    # 2. Extract and validate raw values
    raw_vals = []
    discarded = 0
    clean_records = []
    for r in dedup:
        val = getattr(r, pollutant, None)
        if val is None:
            continue
        cleaned_val, status = DataProcessor.validate_pollutant(pollutant, float(val))
        if status == "invalid" or cleaned_val is None:
            discarded += 1
        else:
            raw_vals.append(cleaned_val)
            clean_records.append((r.recorded_at, cleaned_val))

    # 3. Outlier detection (Modified Z-score using MAD > 3.5)
    final_clean = []
    if len(raw_vals) >= 3:
        s_vals = sorted(raw_vals)
        n = len(s_vals)
        med = s_vals[n // 2] if n % 2 == 1 else (s_vals[n // 2 - 1] + s_vals[n // 2]) / 2.0
        abs_devs = [abs(x - med) for x in raw_vals]
        s_devs = sorted(abs_devs)
        mad = s_devs[n // 2] if n % 2 == 1 else (s_devs[n // 2 - 1] + s_devs[n // 2]) / 2.0

        if mad > 0:
            for r_at, x in clean_records:
                mod_z = 0.6745 * abs(x - med) / mad
                if mod_z > 3.5:
                    discarded += 1
                else:
                    final_clean.append((r_at, x))
        else:
            # Fall back to standard Z-score
            mean_val = sum(raw_vals) / len(raw_vals)
            variance = sum((x - mean_val) ** 2 for x in raw_vals) / len(raw_vals)
            std_dev = math.sqrt(variance)
            if std_dev > 0:
                for r_at, x in clean_records:
                    z_score = abs(x - mean_val) / std_dev
                    if z_score > 3.0:
                        discarded += 1
                    else:
                        final_clean.append((r_at, x))
            else:
                final_clean = list(clean_records)
    else:
        final_clean = list(clean_records)

    # 4. Bin clean values into 1-hour bins
    is_pm = pollutant.lower() in ("pm25", "pm10")
    is_ozone = pollutant.lower() == "o3"
    is_co = pollutant.lower() == "co"
    
    if is_pm:
        window_size = 12
    elif is_ozone or is_co:
        window_size = 8
    else:
        window_size = 3

    hourly_sums = [0.0] * window_size
    hourly_counts = [0] * window_size

    for r_at, val in final_clean:
        age_hours = (now - r_at).total_seconds() / 3600.0
        bin_idx = int(age_hours)
        if 0 <= bin_idx < window_size:
            hourly_sums[bin_idx] += val
            hourly_counts[bin_idx] += 1

    hourly_concentrations = []
    for s, c in zip(hourly_sums, hourly_counts):
        hourly_concentrations.append(s / c if c > 0 else None)

    valid_indices = [i for i, v in enumerate(hourly_concentrations) if v is not None]
    
    if not valid_indices:
        return {
            "concentration": None, "weight": 1.0, "used": 0, "missing": window_size,
            "discarded": discarded, "window": window_size
        }

    used = len(valid_indices)
    missing = window_size - used

    # NowCast algorithm (for PM and Ozone)
    if is_pm or is_ozone:
        recent_valid = [i for i in valid_indices if i < 3]
        if len(recent_valid) < 2:
            # Fall back to latest valid hour concentration
            fallback_conc = hourly_concentrations[valid_indices[0]]
            return {
                "concentration": fallback_conc, "weight": 0.5, "used": used, "missing": missing,
                "discarded": discarded, "window": window_size
            }

        valid_values = [hourly_concentrations[i] for i in valid_indices]
        c_min = min(valid_values)
        c_max = max(valid_values)

        w_star = 1.0 - (c_max - c_min) / c_max if c_max > 0 else 1.0
        weight = max(w_star, 0.5)

        num = sum(hourly_concentrations[i] * (weight ** i) for i in valid_indices)
        den = sum(weight ** i for i in valid_indices)
        concentration = num / den if den > 0 else None

        return {
            "concentration": concentration, "weight": round(weight, 4), "used": used, "missing": missing,
            "discarded": discarded, "window": window_size
        }

    # CO: 8-hour average (requires >= 6 valid hours)
    elif is_co:
        if used >= 6:
            concentration = sum(hourly_concentrations[i] for i in valid_indices) / used
        else:
            concentration = hourly_concentrations[valid_indices[0]]
        return {
            "concentration": concentration, "weight": 1.0, "used": used, "missing": missing,
            "discarded": discarded, "window": window_size
        }

    # NO2, SO2: 1-hour average (search backwards up to 3 hours)
    else:
        concentration = hourly_concentrations[valid_indices[0]]
        return {
            "concentration": concentration, "weight": 1.0, "used": used, "missing": missing,
            "discarded": discarded, "window": window_size
        }


class CurrentAQIService:
    """Service orchestrating CPCB aggregates and fallback strategies directly."""

    def __init__(self, repository: CurrentAQIRepository) -> None:
        self.repository = repository

    async def get_current_aqi(self, city: str) -> CurrentAQIResponse:
        """Query database or trigger fallback sequence to compile current AQI statistics for a city."""
        logger.info(f"Retrieving current AQI for city={city}")
        settings = get_settings()

        # ------------------------------------------------------------------
        # 1. DATABASE PROVIDER LAYER
        # ------------------------------------------------------------------
        db_start = time.perf_counter()
        try:
            logger.info(f"Provider: Database | Started querying city={city}")
            now_utc = datetime.utcnow()
            # Fetch all records in the last 24 hours to cover window.
            # Wrapped in asyncio.to_thread so the synchronous SQLAlchemy call
            # runs in the thread pool and does not block the event loop.
            all_records = await asyncio.to_thread(
                self.repository.get_records_for_city_since,
                city, now_utc - timedelta(hours=24)
            )
            
            if all_records:
                stale_threshold_hours = settings.STALE_THRESHOLD_HOURS
                grace_margin = timedelta(minutes=5)
                
                # Group records by location_name
                by_station = {}
                for r in all_records:
                    loc = r.location_name or "Unknown Station"
                    if loc not in by_station:
                        by_station[loc] = []
                    by_station[loc].append(r)
                
                valid_stations = []
                station_aqis = []
                newest_timestamps = []
                critical_station_record = None
                critical_station_rolling_concentrations = None
                critical_dominant_pollutant = None
                critical_nowcast_stats = None
                max_station_aqi_val = -1.0
                min_station_aqi_val = 9999.0
                
                for loc, records in by_station.items():
                    records_sorted = sorted(records, key=lambda x: x.recorded_at or datetime.min, reverse=True)
                    latest_record = records_sorted[0]
                    
                    if not latest_record.recorded_at:
                        continue
                        
                    is_stale = (now_utc - latest_record.recorded_at) > (timedelta(hours=stale_threshold_hours) + grace_margin)
                    if is_stale:
                        continue
                        
                    newest_timestamps.append(latest_record.recorded_at)
                    
                    # Filter records in the 24-hour window
                    twenty_four_hour_records = [r for r in records_sorted if r.recorded_at and (now_utc - r.recorded_at) <= timedelta(hours=24)]
                    
                    rolling_concentrations = {}
                    nowcast_stats = {}
                    pollutants = ["pm25", "pm10", "no2", "so2", "co", "o3"]
                    
                    for p in pollutants:
                        p_nowcast = compute_nowcast(twenty_four_hour_records, p, now_utc)
                        nowcast_stats[p] = p_nowcast
                        
                        if p_nowcast["concentration"] is not None:
                            rolling_concentrations[p] = p_nowcast["concentration"]
                        else:
                            latest_val = getattr(latest_record, p)
                            if latest_val is not None and latest_val >= 0:
                                rolling_concentrations[p] = latest_val
                            else:
                                rolling_concentrations[p] = None
                                
                    calc_aqi, calc_cat, calc_dom = calculate_overall_aqi(
                        pm25=rolling_concentrations["pm25"],
                        pm10=rolling_concentrations["pm10"],
                        no2=rolling_concentrations["no2"],
                        so2=rolling_concentrations["so2"],
                        co=rolling_concentrations["co"],
                        o3=rolling_concentrations["o3"]
                    )
                    
                    station_aqi_val = calc_aqi
                    if station_aqi_val is None:
                        station_aqi_val = latest_record.aqi if latest_record.aqi is not None else 50.0
                        dominant_pollutant = latest_record.dominant_pollutant or "PM2.5"
                    else:
                        dominant_pollutant = calc_dom or "PM2.5"
                        
                    station_aqis.append(station_aqi_val)
                    if station_aqi_val > max_station_aqi_val:
                        max_station_aqi_val = station_aqi_val
                        critical_station_record = latest_record
                        critical_station_rolling_concentrations = rolling_concentrations
                        critical_dominant_pollutant = dominant_pollutant
                        critical_nowcast_stats = nowcast_stats
                        
                    if station_aqi_val < min_station_aqi_val:
                        min_station_aqi_val = station_aqi_val
                        
                    valid_stations.append({
                        "station_name": loc,
                        "latest_record": latest_record,
                        "rolling_aqi": station_aqi_val,
                        "dominant_pollutant": dominant_pollutant
                    })
                    
                if valid_stations:
                    if settings.CITY_AGGREGATION_METHOD == "average":
                        overall_aqi = round(sum(station_aqis) / len(station_aqis), 2)
                    else:
                        overall_aqi = max_station_aqi_val
                        
                    newest_timestamp = max(newest_timestamps)
                    matched_city = valid_stations[0]["latest_record"].city or city
                    category = get_aqi_category(overall_aqi)
                    
                    # ── NowCast Confidence Scoring ──
                    dom_key = "pm25"
                    if critical_dominant_pollutant:
                        cleaned_dom = critical_dominant_pollutant.lower().replace(".", "")
                        if cleaned_dom in ("pm25", "pm10", "no2", "so2", "co", "o3"):
                            dom_key = cleaned_dom
                            
                    dom_stats = critical_nowcast_stats[dom_key]
                    used_hours = dom_stats["used"]
                    window_hours = dom_stats["window"]
                    
                    # Coverage Score (Max 30)
                    coverage_percent = (used_hours / window_hours * 100.0) if window_hours > 0 else 0.0
                    coverage_score = 3 if coverage_percent >= 75.0 else 2 if coverage_percent >= 25.0 else 1
                    
                    # Freshness Score (Max 30)
                    age_hours = (now_utc - newest_timestamp).total_seconds() / 3600.0
                    freshness_score = 3 if age_hours <= 1.0 else 2 if age_hours <= 3.0 else 1
                    
                    # Data age metadata
                    if age_hours <= 1.0:
                        freshness_status = "fresh"
                    elif age_hours <= stale_threshold_hours / 2:
                        freshness_status = "acceptable"
                    else:
                        freshness_status = "stale"
                    
                    # Completeness Score (Max 30)
                    pollutant_count = sum(1 for p in pollutants if critical_station_rolling_concentrations[p] is not None)
                    completeness_score = 3 if pollutant_count == 6 else 2 if pollutant_count >= 3 else 1
                    
                    avg_score = (coverage_score + freshness_score + completeness_score) / 3.0
                    
                    if avg_score >= 2.5:
                        conf_level_meta = "High"
                        dq_rating_meta = "Excellent"
                        conf_level_response = "high"
                    elif avg_score >= 1.5:
                        conf_level_meta = "Medium"
                        dq_rating_meta = "Good"
                        conf_level_response = "medium"
                    else:
                        conf_level_meta = "Low"
                        dq_rating_meta = "Fair"
                        conf_level_response = "low"
                        
                    window_start_time = now_utc - timedelta(hours=window_hours)
                    
                    metadata = RollingAverageMetadata(
                        aggregation_strategy="nowcast_live",
                        window_hours=window_hours,
                        records_used=used_hours,
                        records_discarded=dom_stats["discarded"],
                        coverage_percent=round(coverage_percent, 1),
                        rolling_window_start=window_start_time.isoformat() + "Z",
                        rolling_window_end=now_utc.isoformat() + "Z",
                        dominant_pollutant=critical_dominant_pollutant,
                        confidence=conf_level_meta,
                        data_quality=dq_rating_meta
                    )
                    
                    db_dur = (time.perf_counter() - db_start) * 1000.0
                    logger.info(
                        f"Provider: Database | Status: Success | NowCast Weight: {dom_stats['weight']} | Duration: {db_dur:.2f}ms | City: {city}"
                    )
                    
                    return CurrentAQIResponse(
                        city=matched_city,
                        aqi=overall_aqi,
                        aqi_category=category or "Unknown",
                        dominant_pollutant=critical_dominant_pollutant,
                        stations_used=len(valid_stations),
                        min_station_aqi=min_station_aqi_val,
                        max_station_aqi=max_station_aqi_val,
                        recorded_at=newest_timestamp,
                        data_age_hours=round(age_hours, 2),
                        freshness_status=freshness_status,
                        source="OpenAQ",
                        fallback_used=False,
                        cpcb_methodology="nowcast_live",
                        confidence=conf_level_response,
                        metadata=metadata,
                        # pollutants
                        pm25=critical_station_rolling_concentrations["pm25"],
                        pm10=critical_station_rolling_concentrations["pm10"],
                        no2=critical_station_rolling_concentrations["no2"],
                        so2=critical_station_rolling_concentrations["so2"],
                        o3=critical_station_rolling_concentrations["o3"],
                        co=critical_station_rolling_concentrations["co"],
                        # weather
                        temperature=critical_station_record.temperature,
                        humidity=critical_station_record.humidity,
                        wind_speed=critical_station_record.wind_speed,
                        wind_direction=critical_station_record.wind_direction,
                        pressure=critical_station_record.pressure,
                        # coordinates
                        latitude=critical_station_record.latitude or 0.0,
                        longitude=critical_station_record.longitude or 0.0
                    )
            
            db_dur = (time.perf_counter() - db_start) * 1000.0
            logger.info(
                f"Provider: Database | Status: Skip (No fresh data) | Duration: {db_dur:.2f}ms | City: {city}"
            )
        except Exception as e:
            db_dur = (time.perf_counter() - db_start) * 1000.0
            safe_err = str(e).encode("ascii", "ignore").decode("ascii")
            logger.warning(
                f"Provider: Database | Status: Failure | Reason: {safe_err} | Duration: {db_dur:.2f}ms | City: {city}"
            )

        # ------------------------------------------------------------------
        # GEOCODING RESOLUTION (Required for external fallback)
        # ------------------------------------------------------------------
        logger.info(f"Initiating Nominatim geocoding lookup for city={city}")
        coords = await NominatimGeocoderClient.geocode_address(city, "")
        if not coords:
            logger.warning(f"Geocoding failed for fallback city={city}")
            raise HTTPException(
                status_code=404,
                detail=f"No current AQI data found for city '{city}' in the last 24 hours, and location geocoding failed."
            )
        lat, lon = coords

        # ------------------------------------------------------------------
        # 2. OPEN-METEO FALLBACK LAYER (Last Resort)
        # ------------------------------------------------------------------
        openmeteo_start = time.perf_counter()
        logger.info(f"Provider: Open-Meteo | Started querying city={city}")
        
        aq_client = OpenMeteoAirQualityClient()
        weather_client = OpenMeteoWeatherClient()

        async def safe_fetch_aq():
            try:
                return await aq_client.fetch_air_quality(lat, lon)
            except Exception as e:
                safe_err = str(e).encode("ascii", "ignore").decode("ascii")
                logger.warning(f"Fallback Open-Meteo Air Quality query failed: {safe_err}")
                return None

        async def safe_fetch_weather():
            try:
                return await weather_client.fetch_current_weather(lat, lon)
            except Exception as e:
                safe_err = str(e).encode("ascii", "ignore").decode("ascii")
                logger.warning(f"Fallback Open-Meteo Forecast query failed: {safe_err}")
                return None

        aq_data, weather_data = await asyncio.gather(safe_fetch_aq(), safe_fetch_weather())

        if aq_data is None and weather_data is None:
            openmeteo_dur = (time.perf_counter() - openmeteo_start) * 1000.0
            logger.error(
                f"Provider: Open-Meteo | Status: Failure | Reason: Both API queries failed | Duration: {openmeteo_dur:.2f}ms | City: {city}"
            )
            if all_records:
                logger.warning(f"Open-Meteo failed. Falling back to stale database records (count={len(all_records)}) for city={city}")
                station_aqis = [r.aqi if r.aqi is not None else 50.0 for r in all_records]
                max_aqi = max(station_aqis)
                min_aqi = min(station_aqis)
                critical_record = sorted(all_records, key=lambda x: x.recorded_at)[-1]
                newest_timestamp = max(r.recorded_at for r in all_records if r.recorded_at is not None)
                category = get_aqi_category(max_aqi)
                
                metadata = RollingAverageMetadata(
                    aggregation_strategy="stale_database_fallback",
                    window_hours=12,
                    records_used=1,
                    records_discarded=0,
                    coverage_percent=100.0,
                    rolling_window_start=(newest_timestamp - timedelta(hours=12)).isoformat() + "Z",
                    rolling_window_end=newest_timestamp.isoformat() + "Z",
                    dominant_pollutant=critical_record.dominant_pollutant or "PM2.5",
                    confidence="Low",
                    data_quality="Poor"
                )
                
                stale_age_hours = (now_utc - newest_timestamp).total_seconds() / 3600.0
                return CurrentAQIResponse(
                    city=critical_record.city or city,
                    aqi=max_aqi,
                    aqi_category=category or "Unknown",
                    dominant_pollutant=critical_record.dominant_pollutant,
                    stations_used=len(all_records),
                    min_station_aqi=min_aqi,
                    max_station_aqi=max_aqi,
                    recorded_at=newest_timestamp,
                    data_age_hours=round(stale_age_hours, 2),
                    freshness_status="stale",
                    source="OpenAQ",
                    fallback_used=True,
                    cpcb_methodology="instantaneous_estimate",
                    confidence="low",
                    metadata=metadata,
                    pm25=critical_record.pm25,
                    pm10=critical_record.pm10,
                    no2=critical_record.no2,
                    so2=critical_record.so2,
                    o3=critical_record.o3,
                    co=critical_record.co,
                    temperature=critical_record.temperature,
                    humidity=critical_record.humidity,
                    wind_speed=critical_record.wind_speed,
                    wind_direction=critical_record.wind_direction,
                    pressure=critical_record.pressure,
                    latitude=critical_record.latitude or 0.0,
                    longitude=critical_record.longitude or 0.0
                )
            raise HTTPException(
                status_code=502,
                detail=f"Failed to fetch fallback data for city '{city}' from Open-Meteo."
            )

        pm25 = None
        pm10 = None
        no2 = None
        so2 = None
        o3 = None
        co = None

        if aq_data and "current" in aq_data:
            current_aq = aq_data["current"]
            pm25 = current_aq.get("pm2_5")
            pm10 = current_aq.get("pm10")
            no2 = current_aq.get("nitrogen_dioxide")
            so2 = current_aq.get("sulphur_dioxide")
            o3 = current_aq.get("ozone")
            
            raw_co = current_aq.get("carbon_monoxide")
            co = raw_co / 1000.0 if raw_co is not None else None

        calc_res = calculate_overall_aqi(pm25=pm25, pm10=pm10, no2=no2, so2=so2, co=co, o3=o3)
        aqi_val, category, dominant_pollutant = calc_res
        
        if aqi_val is None:
            openmeteo_dur = (time.perf_counter() - openmeteo_start) * 1000.0
            logger.warning(
                f"Provider: Open-Meteo | Status: Failure | Reason: AQI calculation failed | Duration: {openmeteo_dur:.2f}ms | City: {city}"
            )
            raise HTTPException(
                status_code=404,
                detail=f"No current AQI data found for city '{city}' and fallback Open-Meteo API query failed."
            )

        temperature = None
        humidity = None
        wind_speed = None
        wind_direction = None
        pressure = None

        if weather_data and "current" in weather_data:
            current_w = weather_data["current"]
            temperature = current_w.get("temperature_2m")
            humidity = current_w.get("relative_humidity_2m")
            wind_speed = current_w.get("wind_speed_10m")
            wind_direction = current_w.get("wind_direction_10m")
            pressure = current_w.get("surface_pressure")

        recorded_at = datetime.utcnow()
        if aq_data and "current" in aq_data and aq_data["current"].get("time"):
            try:
                recorded_at = datetime.fromisoformat(aq_data["current"]["time"].replace("Z", ""))
            except Exception:
                pass

        openmeteo_dur = (time.perf_counter() - openmeteo_start) * 1000.0
        logger.info(
            f"Provider: Open-Meteo | Status: Success | Duration: {openmeteo_dur:.2f}ms | City: {city}"
        )

        metadata = RollingAverageMetadata(
            aggregation_strategy="instantaneous_estimate",
            window_hours=1,
            records_used=1,
            records_discarded=0,
            coverage_percent=100.0,
            rolling_window_start=recorded_at.isoformat() + "Z",
            rolling_window_end=recorded_at.isoformat() + "Z",
            dominant_pollutant=dominant_pollutant or "PM2.5",
            confidence="Low",
            data_quality="Poor"
        )

        return CurrentAQIResponse(
            city=city,
            aqi=aqi_val,
            aqi_category=category or "Unknown",
            dominant_pollutant=dominant_pollutant,
            stations_used=0,
            min_station_aqi=aqi_val,
            max_station_aqi=aqi_val,
            recorded_at=recorded_at,
            data_age_hours=0.0,
            freshness_status="fresh",
            source="open_meteo",
            fallback_used=True,
            cpcb_methodology="instantaneous_estimate",
            confidence="low",
            metadata=metadata,
            # pollutants
            pm25=pm25,
            pm10=pm10,
            no2=no2,
            so2=so2,
            o3=o3,
            # weather
            co=co,
            temperature=temperature,
            humidity=humidity,
            wind_speed=wind_speed,
            wind_direction=wind_direction,
            pressure=pressure,
            # coordinates
            latitude=lat,
            longitude=lon
        )

    async def get_current_aqi_diagnostics(self, city: str) -> dict:
        """Expose the complete internal calculation pipeline for a city's current AQI with NowCast live weighting."""
        logger.info(f"Diagnostics requested for city={city}")
        now_utc = datetime.utcnow()
        settings = get_settings()
        
        all_records = await asyncio.to_thread(
            self.repository.get_records_for_city_since,
            city, now_utc - timedelta(hours=24)
        )
        
        station_diagnostics = []
        station_aqis = []
        
        if all_records:
            stale_threshold_hours = settings.STALE_THRESHOLD_HOURS
            grace_margin = timedelta(minutes=5)
            
            # Group records by location_name
            by_station = {}
            for r in all_records:
                loc = r.location_name or "Unknown Station"
                if loc not in by_station:
                    by_station[loc] = []
                by_station[loc].append(r)
                
            for loc, records in by_station.items():
                records_sorted = sorted(records, key=lambda x: x.recorded_at or datetime.min, reverse=True)
                latest_record = records_sorted[0]
                
                if not latest_record.recorded_at:
                    continue
                    
                is_stale = (now_utc - latest_record.recorded_at) > (timedelta(hours=stale_threshold_hours) + grace_margin)
                
                # Filter records in the 24-hour window
                twenty_four_hour_records = [r for r in records_sorted if r.recorded_at and (now_utc - r.recorded_at) <= timedelta(hours=24)]
                
                rolling_concentrations = {}
                nowcast_stats = {}
                pollutants = ["pm25", "pm10", "no2", "so2", "co", "o3"]
                
                station_records_count = 0
                
                for p in pollutants:
                    p_nowcast = compute_nowcast(twenty_four_hour_records, p, now_utc)
                    nowcast_stats[p] = p_nowcast
                    station_records_count = max(station_records_count, p_nowcast["used"])
                    
                    if p_nowcast["concentration"] is not None:
                        rolling_concentrations[p] = p_nowcast["concentration"]
                    else:
                        latest_val = getattr(latest_record, p)
                        if latest_val is not None and latest_val >= 0:
                            rolling_concentrations[p] = latest_val
                        else:
                            rolling_concentrations[p] = None
                
                # Calculate instantaneous AQI
                inst_aqi, inst_cat, inst_dom = calculate_overall_aqi(
                    pm25=latest_record.pm25, pm10=latest_record.pm10, no2=latest_record.no2,
                    so2=latest_record.so2, co=latest_record.co, o3=latest_record.o3
                )
                if inst_aqi is None:
                    inst_aqi = latest_record.aqi if latest_record.aqi is not None else 50.0
                    inst_dom = latest_record.dominant_pollutant or "PM2.5"
                
                # Calculate rolling NowCast AQI
                roll_aqi, roll_cat, roll_dom = calculate_overall_aqi(
                    pm25=rolling_concentrations["pm25"], pm10=rolling_concentrations["pm10"],
                    no2=rolling_concentrations["no2"], so2=rolling_concentrations["so2"],
                    co=rolling_concentrations["co"], o3=rolling_concentrations["o3"]
                )
                if roll_aqi is None:
                    roll_aqi = latest_record.aqi if latest_record.aqi is not None else 50.0
                    roll_dom = latest_record.dominant_pollutant or "PM2.5"
                
                # Determine methodology and confidence
                methodology = "nowcast_live" if station_records_count > 0 else "instantaneous_fallback"
                confidence = "High" if station_records_count >= 10 else "Medium" if station_records_count >= 4 else "Low"
                
                station_data = {
                    "station_name": loc,
                    "coordinates": {
                        "latitude": latest_record.latitude,
                        "longitude": latest_record.longitude
                    },
                    "measurements_used": station_records_count,
                    "measurement_timestamps": [r.recorded_at.isoformat() for r in twenty_four_hour_records if r.recorded_at],
                    "rolling_average_pollutant_concentrations": rolling_concentrations,
                    "nowcast_statistics": nowcast_stats,
                    "instantaneous_pollutant_concentrations": {
                        "pm25": latest_record.pm25,
                        "pm10": latest_record.pm10,
                        "no2": latest_record.no2,
                        "so2": latest_record.so2,
                        "co": latest_record.co,
                        "o3": latest_record.o3
                    },
                    "instantaneous_aqi": inst_aqi,
                    "rolling_aqi": roll_aqi,
                    "dominant_pollutant": roll_dom or "PM2.5",
                    "calculation_methodology": methodology,
                    "confidence_level": confidence,
                    "is_stale_in_db": is_stale
                }
                
                station_diagnostics.append(station_data)
                
                if not is_stale:
                    station_aqis.append(roll_aqi)
        
        final_aqi = None
        aggregation_result = {}
        if station_aqis:
            if settings.CITY_AGGREGATION_METHOD == "average":
                final_aqi = round(sum(station_aqis) / len(station_aqis), 2)
            else:
                final_aqi = max(station_aqis)
            aggregation_result = {
                "active_stations_aqis": station_aqis,
                "min_station_aqi": min(station_aqis),
                "max_station_aqi": max(station_aqis),
                "stations_used_count": len(station_aqis),
                "aggregation_method": settings.CITY_AGGREGATION_METHOD,
                "average_station_aqi": round(sum(station_aqis) / len(station_aqis), 2)
            }
        
        return {
            "city": city,
            "timestamp_utc": datetime.utcnow().isoformat(),
            "stations_found": len(station_diagnostics),
            "stations": station_diagnostics,
            "aggregation": aggregation_result,
            "final_city_aqi": final_aqi,
            "final_city_category": get_aqi_category(final_aqi) if final_aqi is not None else "Unknown"
        }
