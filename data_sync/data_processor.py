"""Pure, stateless data processing and validation prep helpers for air quality and weather telemetry."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, Tuple, Optional

from database.schemas.aqi_data import AQIDataValidate
from services.dominant_pollutant import calculate_overall_aqi
from api_layer.logging import get_logger

logger = get_logger(__name__)


# Normalizer map for spelling variations
CITY_SPELLING_MAP = {
    "bombay": "Mumbai",
    "calcutta": "Kolkata",
    "madras": "Chennai",
    "bangalore": "Bengaluru",
    "gurgaon": "Gurugram",
    "cochin": "Kochi",
    "trivandrum": "Thiruvananthapuram",
    "pondicherry": "Puducherry",
    "vizag": "Visakhapatnam",
    "banaras": "Varanasi",
    "benaras": "Varanasi",
    "gauhati": "Guwahati",
    "trichy": "Tiruchirappalli",
}

# Set of known canonical cities in India (comprehensive active monitoring cities list)
CANONICAL_CITIES = {
    "Delhi", "New Delhi", "Mumbai", "Bengaluru", "Hyderabad", "Chennai", "Kolkata",
    "Pune", "Ahmedabad", "Jaipur", "Surat", "Patna", "Lucknow", "Kanpur", "Gurugram",
    "Noida", "Jammu", "Srinagar", "Beed", "Hingoli", "Dombivli", "Ambernath",
    "Vijayawada", "Virudhunagar", "Pudukottai", "Jabalpur", "Ghaziabad", "Pimpri-Chinchwad",
    "Asansol", "Namakkal", "Rajkot", "Raebareli", "Durgapur", "Bhiwadi", "Bhavnagar",
    "Howrah", "Mehsana", "Vadodara", "Ulhasnagar", "Gaya", "Rohtak", "Haldia", "Jodhpur",
    "Indore", "Bhopal", "Visakhapatnam", "Coimbatore", "Cuttack", "Belagavi", "Meerut",
    "Bareilly", "Chandigarh", "Latur", "Khunmoh", "Barbil", "Owan", "Jajpur Road",
    "Bampada", "Byrnihat", "Vasai-Virar", "Bamebari", "Keezhakottaiyur", "Jalore",
    "Dungarpur", "Thirupparankundram", "Hubli", "Barrackpore", "Sagar", "Shillong",
    "Durgachak", "Baranagar", "Darbhanga", "Sewri", "Bhilai", "Chandrapur", "Loni",
    "Bhiwandi", "Hosur", "Kaithal", "Boisar", "Udupi", "Honnenahalli", "Bidar",
    "Parbhani", "Dhule", "Jalgaon", "Firozabad", "Sangli", "Baran", "Nanded",
    "Muzaffarpur", "Mahad", "Nagaur", "Ahilyanagar", "Sonipat", "Jhalawar",
    "Bhilwara", "Bundi", "Jaisalmer", "Akola", "Sikar", "Badlapur", "Sri Ganganagar",
    "Barmer", "Khairthal", "Hanumangarh", "Dausa", "Eluru", "Palwal", "Sawai Madhopur",
    "Fatehpur Sikri", "Jhunjhunu", "Aurangabad", "Guntur", "Puducherry", "Kochi",
    "Thiruvananthapuram", "Guwahati", "Varanasi", "Tiruchirappalli", "Kanchipuram",
    "Vellore", "Salem", "Tiruppur", "Erode", "Madurai", "Tirunelveli", "Tuticorin",
    "Mysuru", "Mangaluru", "Belgaum", "Dharwad", "Gulbarga", "Davangere", "Bellary",
    "Shimoga", "Tumakuru", "Karnal", "Panipat", "Ambala", "Yamunanagar", "Kharar",
    "Panchkula", "Hisar", "Roorkee", "Dehradun", "Haridwar", "Haldwani", "Rudrapur",
    "Amritsar", "Ludhiana", "Jalandhar", "Patiala", "Bathinda", "Hoshiarpur",
    "Pathankot", "Moga", "Ajmer", "Udaipur", "Bikaner", "Kota", "Alwar",
    "Bharatpur", "Sikar", "Pali", "Gandhinagar", "Bhavnagar", "Jamnagar", "Junagadh",
    "Gandhidham", "Anand", "Navsari", "Morbi", "Nadiad", "Bharuch", "Porbandar",
    "Nashik", "Nagpur", "Thane", "Solapur", "Kolkata", "Howrah", "Siliguri",
    "Asansol", "Durgapur", "Kharagpur", "Haldia", "Bardhaman", "Malda",
    "Bhubaneswar", "Rourkela", "Sambalpur", "Puri", "Balasore", "Bhadrak",
    "Raipur", "Bhilai", "Bilaspur", "Korba", "Rajnandgaon", "Jagdalpur",
    "Ranchi", "Jamshedpur", "Dhanbad", "Bokaro", "Deoghar", "Hazaribagh",
    "Gwalior", "Jabalpur", "Ujjain", "Sagar", "Dewas", "Satna", "Ratlam",
    "Agra", "Varanasi", "Allahabad", "Prayagraj", "Meerut", "Bareilly",
    "Aligarh", "Moradabad", "Saharanpur", "Gorakhpur", "Noida", "Firozabad",
    "Jhansi", "Muzaffarnagar", "Mathura", "Ayodhya", "Mirzapur",
    "Gaya", "Bhagalpur", "Muzaffarpur", "Purnia", "Darbhanga", "Bihar Sharif",
    "Arrah", "Begusarai", "Katihar", "Munger", "Dadri", "Chhapra"
}


def extract_city_from_name(name: str) -> str:
    """Robust parsing engine that extracts city name from India station location names."""
    if not name:
        return "Unknown"
    
    # 1. Clean monitoring board suffix and extra whitespaces
    clean_name = re.sub(
        r"\s*-\s*(?:CPCB|SPCB|IMD|DPCC|CPCC|OSPCB|WBPCB|KSPCB|TSPCB|BSPCB|RSPCB|HSPCB|UPPCB|MPCB|APPCB|GPCB|HPPCB|JKPCB|PPCB|UKPCB|OSPCB|TNPCB)\s*$", 
        "", 
        name, 
        flags=re.IGNORECASE
    )
    clean_name = clean_name.strip()
    
    # 2. Hardcoded specific overrides (e.g. Koramangala in Bengaluru, Bellandur in Bengaluru)
    clean_lower = clean_name.lower()
    if "koramangala" in clean_lower or "bellandur" in clean_lower or "peenya" in clean_lower:
        return "Bengaluru"
    if "auroville" in clean_lower:
        return "Puducherry"
    if "igi airport" in clean_lower:
        return "Delhi"
        
    # 3. Normalization function helper
    def normalize_word(word: str) -> Optional[str]:
        w_cleaned = word.strip().lower()
        # Remove any non-alphabetic chars except spaces/hyphens
        w_cleaned = re.sub(r"[^a-zA-Z\s\-]", "", w_cleaned).strip()
        if not w_cleaned or len(w_cleaned) < 3:
            return None
        
        # Check spelling variations first
        if w_cleaned in CITY_SPELLING_MAP:
            return CITY_SPELLING_MAP[w_cleaned]
            
        # Check in canonical set
        for canon in CANONICAL_CITIES:
            if canon.lower() == w_cleaned:
                return canon
        return w_cleaned.title()

    # 4. Parse comma-delimited strings (e.g., "Sanjay Nagar, Ghaziabad")
    if "," in clean_name:
        parts = [p.strip() for p in clean_name.split(",")]
        # Examine from right to left
        for part in reversed(parts):
            norm = normalize_word(part)
            if norm and norm in CANONICAL_CITIES:
                return norm
            # Check if part contains a substring that is canonical
            for canon in CANONICAL_CITIES:
                if re.search(rf"\b{re.escape(canon)}\b", part, re.IGNORECASE):
                    return canon

    # 5. Parse hyphen-delimited strings (e.g., "Sector-18, Panipat")
    if " - " in clean_name:
        parts = [p.strip() for p in clean_name.split(" - ")]
        for part in reversed(parts):
            norm = normalize_word(part)
            if norm and norm in CANONICAL_CITIES:
                return norm

    # 6. Check for single-word substring match in the clean name
    # We sort by length descending to match longer names first (e.g., New Delhi before Delhi)
    sorted_canonical = sorted(list(CANONICAL_CITIES), key=len, reverse=True)
    for canon in sorted_canonical:
        # Match as a distinct word boundary
        if re.search(rf"\b{re.escape(canon)}\b", clean_name, re.IGNORECASE):
            return canon
            
    # 7. Fallback to standard word splitting check
    words = re.split(r"[\s,\-\(\)]+", clean_name)
    for word in words:
        norm = normalize_word(word)
        if norm and norm in CANONICAL_CITIES:
            return norm

    return "Unknown"


class DataProcessor:
    """Stateless utility class to parse, clean, and validate telemetry updates."""

    @staticmethod
    def validate_pollutant(param: str, value: float) -> Tuple[Optional[float], str]:
        """Validate pollutant concentration and return (cleaned_value, status)."""
        if param in ("temperature", "humidity"):
            if param == "humidity" and (value < 0 or value > 100):
                return None, "invalid"
            return value, "valid"

        if value < 0:
            return None, "invalid"

        valid_ranges = {
            "pm25": {"max_valid": 500.0, "max_suspicious": 1000.0},
            "pm10": {"max_valid": 600.0, "max_suspicious": 1200.0},
            "no2": {"max_valid": 400.0, "max_suspicious": 1000.0},
            "so2": {"max_valid": 800.0, "max_suspicious": 2000.0},
            "co": {"max_valid": 34.0, "max_suspicious": 100.0},
            "o3": {"max_valid": 300.0, "max_suspicious": 1000.0},
        }

        ranges = valid_ranges.get(param.lower())
        if not ranges:
            return value, "valid"

        if value <= ranges["max_valid"]:
            return value, "valid"
        elif value <= ranges["max_suspicious"]:
            return value, "suspicious"
        else:
            return None, "invalid"

    @staticmethod
    def extract_city(raw_loc: dict, resolved_city: Optional[str]) -> str:
        """Resolve the city context from locality, geocoding fallback, or name parsing."""
        city = raw_loc.get("locality") or (raw_loc.get("city", {}) or {}).get("name")
        if not city or city.lower() == "unknown":
            if resolved_city:
                return resolved_city
            return extract_city_from_name(raw_loc.get("name") or "")
        return city

    @staticmethod
    def parse_sensor_map(raw_loc: dict) -> Dict[int, Tuple[str, str]]:
        """Map OpenAQ sensor IDs to their respective parameter names and units."""
        sensor_map = {}
        for sensor in (raw_loc.get("sensors") or []):
            if not sensor:
                continue
            s_id = sensor.get("id")
            param = sensor.get("parameter", {}) or {}
            param_name = param.get("name")
            unit = param.get("units") or ""
            if s_id and param_name:
                sensor_map[s_id] = (param_name.lower(), unit.lower())
        return sensor_map

    @staticmethod
    def process_measurements(
        meas_results: list,
        sensor_map: Dict[int, Any]
    ) -> Tuple[Dict[str, Optional[float]], Optional[datetime]]:
        """Extract pollutant values and the latest measurement timestamp.
        
        Implements obsolete sensor filtering (rejecting measurements >2 hours older 
        than the newest measurement in the batch) and CO unit scaling.
        """
        pollutants = {
            "pm25": None, "pm10": None, "no2": None, "o3": None, "co": None, "so2": None,
            "temperature": None, "humidity": None
        }
        pollutant_times = {}
        recorded_at = None

        # Pass 1: Parse and find the latest measurement timestamp in the batch
        latest_time = None
        for m in meas_results:
            date_utc_str = (m.get("datetime", {}) or {}).get("utc")
            if date_utc_str:
                try:
                    t = datetime.fromisoformat(date_utc_str.replace("Z", "+00:00"))
                    if latest_time is None or t > latest_time:
                        latest_time = t
                except (ValueError, TypeError):
                    pass

        # Set recorded_at to the latest timestamp found
        recorded_at = latest_time

        # Pass 2: Process measurements
        for m in meas_results:
            s_id = m.get("sensorsId")
            val = m.get("value")
            if val is None:
                continue

            param_info = sensor_map.get(s_id, "") if s_id else ""
            if isinstance(param_info, tuple):
                param_name, unit = param_info
            else:
                param_name = param_info
                unit = ""

            date_utc_str = (m.get("datetime", {}) or {}).get("utc")
            if not date_utc_str:
                continue

            try:
                m_time = datetime.fromisoformat(date_utc_str.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                continue

            # Reject stale sensor measurements (older than latest_time by > 2 hours)
            if latest_time and (latest_time - m_time).total_seconds() > 7200:
                logger.warning(
                    "Rejecting stale sensor measurement: sensor %s, param %s, unit %s, time %s (latest was %s)",
                    s_id, param_name, unit, m_time.isoformat(), latest_time.isoformat()
                )
                continue

            val = float(val)
            normalized_param = None
            if param_name in ("pm25", "pm2.5"):
                normalized_param = "pm25"
            elif param_name == "pm10":
                normalized_param = "pm10"
            elif param_name == "no2":
                normalized_param = "no2"
            elif param_name == "o3":
                normalized_param = "o3"
            elif param_name == "co":
                normalized_param = "co"
            elif param_name == "so2":
                normalized_param = "so2"
            elif param_name == "temperature":
                normalized_param = "temperature"
            elif param_name in ("relativehumidity", "humidity"):
                normalized_param = "humidity"

            if normalized_param:
                # Deduplicate and prevent overwriting fresh values with older ones
                existing_time = pollutant_times.get(normalized_param)
                if existing_time is None or m_time > existing_time:
                    # Unit conversion for CO (target unit: mg/m³)
                    if normalized_param == "co":
                        scaled_val = val
                        unit_lower = unit.lower()
                        if "ug" in unit_lower or "µg" in unit_lower:
                            scaled_val = val / 1000.0
                            logger.info("Scaling CO from µg/m³ to mg/m³: %f -> %f", val, scaled_val)
                        elif "ppb" in unit_lower:
                            scaled_val = val * 0.001145
                            logger.info("Scaling CO from ppb to mg/m³: %f -> %f", val, scaled_val)
                        elif "ppm" in unit_lower:
                            scaled_val = val * 1.145
                            logger.info("Scaling CO from ppm to mg/m³: %f -> %f", val, scaled_val)
                        val = scaled_val

                    # Unit conversion for NO₂ (target unit: µg/m³)
                    # MW=46.01 → 1 ppb = 1.882 µg/m³ at 25°C, 1 atm
                    elif normalized_param == "no2":
                        unit_lower = unit.lower()
                        if "ppb" in unit_lower:
                            scaled_val = val * 1.882
                            logger.info("Scaling NO2 from ppb to µg/m³: %f -> %f", val, scaled_val)
                            val = scaled_val
                        elif "ppm" in unit_lower:
                            scaled_val = val * 1882.0
                            logger.info("Scaling NO2 from ppm to µg/m³: %f -> %f", val, scaled_val)
                            val = scaled_val

                    # Unit conversion for SO₂ (target unit: µg/m³)
                    # MW=64.06 → 1 ppb = 2.620 µg/m³ at 25°C, 1 atm
                    elif normalized_param == "so2":
                        unit_lower = unit.lower()
                        if "ppb" in unit_lower:
                            scaled_val = val * 2.620
                            logger.info("Scaling SO2 from ppb to µg/m³: %f -> %f", val, scaled_val)
                            val = scaled_val
                        elif "ppm" in unit_lower:
                            scaled_val = val * 2620.0
                            logger.info("Scaling SO2 from ppm to µg/m³: %f -> %f", val, scaled_val)
                            val = scaled_val

                    # Unit conversion for O₃ (target unit: µg/m³)
                    # MW=48.00 → 1 ppb = 1.963 µg/m³ at 25°C, 1 atm
                    elif normalized_param == "o3":
                        unit_lower = unit.lower()
                        if "ppb" in unit_lower:
                            scaled_val = val * 1.963
                            logger.info("Scaling O3 from ppb to µg/m³: %f -> %f", val, scaled_val)
                            val = scaled_val
                        elif "ppm" in unit_lower:
                            scaled_val = val * 1963.0
                            logger.info("Scaling O3 from ppm to µg/m³: %f -> %f", val, scaled_val)
                            val = scaled_val

                    # Outlier validation check
                    validated_val, status = DataProcessor.validate_pollutant(normalized_param, val)
                    if status == "suspicious":
                        logger.warning(
                            "Suspicious pollutant value detected during ingestion: %s = %f (unit: %s)",
                            normalized_param, val, unit
                        )
                        val = validated_val
                    elif status == "invalid":
                        logger.error(
                            "Invalid/corrupted pollutant value rejected during ingestion: %s = %f (unit: %s). Skipping value.",
                            normalized_param, val, unit
                        )
                        continue

                    pollutants[normalized_param] = val
                    pollutant_times[normalized_param] = m_time

        # If all CPCB pollutants are None, raise ValueError to skip corrupted record
        cpcb_pollutants = ["pm25", "pm10", "no2", "o3", "co", "so2"]
        if all(pollutants[p] is None for p in cpcb_pollutants):
            raise ValueError("All pollutant measurements are invalid or None")

        return pollutants, recorded_at

    @staticmethod
    def merge_weather(
        pollutants: Dict[str, Optional[float]],
        weather_res: dict
    ) -> Dict[str, Optional[float]]:
        """Combine pollutant weather values with batch weather forecast coordinates."""
        weather = {
            "wind_speed": None, "wind_direction": None, "precipitation": None, "pressure": None,
            "temperature": pollutants["temperature"], "humidity": pollutants["humidity"]
        }
        current_weather = weather_res.get("current", {})
        if current_weather:
            weather["wind_speed"] = current_weather.get("wind_speed_10m")
            weather["wind_direction"] = current_weather.get("wind_direction_10m")
            weather["precipitation"] = current_weather.get("precipitation")
            weather["pressure"] = current_weather.get("surface_pressure")
            # Fallback temperature and humidity if not retrieved from OpenAQ
            if weather["temperature"] is None:
                weather["temperature"] = current_weather.get("temperature_2m")
            if weather["humidity"] is None:
                weather["humidity"] = current_weather.get("relative_humidity_2m")
        return weather

    @staticmethod
    def validate_record(
        city: str,
        location_name: str,
        latitude: float,
        longitude: float,
        pollutants: Dict[str, Optional[float]],
        weather: Dict[str, Optional[float]],
        recorded_at: Optional[datetime]
    ) -> AQIDataValidate:
        """Calculate standard AQI and prepare validated schema object."""
        aqi_val, aqi_cat, dom_poll = calculate_overall_aqi(
            pm25=pollutants["pm25"], pm10=pollutants["pm10"], no2=pollutants["no2"],
            so2=pollutants["so2"], co=pollutants["co"], o3=pollutants["o3"]
        )

        data_dict = {
            "city": city,
            "location_name": location_name,
            "latitude": latitude,
            "longitude": longitude,
            "pm25": pollutants["pm25"],
            "pm10": pollutants["pm10"],
            "no2": pollutants["no2"],
            "o3": pollutants["o3"],
            "co": pollutants["co"],
            "so2": pollutants["so2"],
            "temperature": weather["temperature"],
            "humidity": weather["humidity"],
            "wind_speed": weather["wind_speed"],
            "wind_direction": weather["wind_direction"],
            "precipitation": weather["precipitation"],
            "pressure": weather["pressure"],
            "recorded_at": recorded_at,
            "aqi": aqi_val,
            "aqi_category": aqi_cat,
            "dominant_pollutant": dom_poll,
        }
        return AQIDataValidate(**data_dict)
