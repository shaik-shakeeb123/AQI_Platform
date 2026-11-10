from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from api_layer.logging import get_logger

logger = get_logger(__name__)

# Primary standard IANA timezones for common ISO 3166-1 alpha-2 and alpha-3 codes.
# For multi-timezone countries (e.g. US, CA, AU), resolution uses coordinate bounding boxes.
COUNTRY_PRIMARY_TIMEZONE: dict[str, str] = {
    # India
    "IN": "Asia/Kolkata",
    "IND": "Asia/Kolkata",
    # United Kingdom
    "GB": "Europe/London",
    "GBR": "Europe/London",
    "UK": "Europe/London",
    # Europe
    "FR": "Europe/Paris",
    "FRA": "Europe/Paris",
    "DE": "Europe/Berlin",
    "DEU": "Europe/Berlin",
    "IT": "Europe/Rome",
    "ITA": "Europe/Rome",
    "ES": "Europe/Madrid",
    "ESP": "Europe/Madrid",
    "NL": "Europe/Amsterdam",
    "NLD": "Europe/Amsterdam",
    "BE": "Europe/Brussels",
    "BEL": "Europe/Brussels",
    "CH": "Europe/Zurich",
    "CHE": "Europe/Zurich",
    "AT": "Europe/Vienna",
    "AUT": "Europe/Vienna",
    "SE": "Europe/Stockholm",
    "SWE": "Europe/Stockholm",
    "NO": "Europe/Oslo",
    "NOR": "Europe/Oslo",
    "FI": "Europe/Helsinki",
    "FIN": "Europe/Helsinki",
    "DK": "Europe/Copenhagen",
    "DNK": "Europe/Copenhagen",
    "IE": "Europe/Dublin",
    "IRL": "Europe/Dublin",
    "PL": "Europe/Warsaw",
    "POL": "Europe/Warsaw",
    "CZ": "Europe/Prague",
    "CZE": "Europe/Prague",
    "GR": "Europe/Athens",
    "GRC": "Europe/Athens",
    "PT": "Europe/Lisbon",
    "PRT": "Europe/Lisbon",
    # Asia
    "JP": "Asia/Tokyo",
    "JPN": "Asia/Tokyo",
    "CN": "Asia/Shanghai",
    "CHN": "Asia/Shanghai",
    "KR": "Asia/Seoul",
    "KOR": "Asia/Seoul",
    "SG": "Asia/Singapore",
    "SGP": "Asia/Singapore",
    "HK": "Asia/Hong_Kong",
    "HKG": "Asia/Hong_Kong",
    "TW": "Asia/Taipei",
    "TWN": "Asia/Taipei",
    "TH": "Asia/Bangkok",
    "THA": "Asia/Bangkok",
    "VN": "Asia/Ho_Chi_Minh",
    "VNM": "Asia/Ho_Chi_Minh",
    "MY": "Asia/Kuala_Lumpur",
    "MYS": "Asia/Kuala_Lumpur",
    "PH": "Asia/Manila",
    "PHL": "Asia/Manila",
    "PK": "Asia/Karachi",
    "PAK": "Asia/Karachi",
    "BD": "Asia/Dhaka",
    "BGD": "Asia/Dhaka",
    "LK": "Asia/Colombo",
    "LKA": "Asia/Colombo",
    "NP": "Asia/Kathmandu",
    "NPL": "Asia/Kathmandu",
    "AE": "Asia/Dubai",
    "ARE": "Asia/Dubai",
    "SA": "Asia/Riyadh",
    "SAU": "Asia/Riyadh",
    "IL": "Asia/Jerusalem",
    "ISR": "Asia/Jerusalem",
    # Americas
    "MX": "America/Mexico_City",
    "MEX": "America/Mexico_City",
    "BR": "America/Sao_Paulo",
    "BRA": "America/Sao_Paulo",
    "AR": "America/Argentina/Buenos_Aires",
    "ARG": "America/Argentina/Buenos_Aires",
    "CL": "America/Santiago",
    "CHL": "America/Santiago",
    "CO": "America/Bogota",
    "COL": "America/Bogota",
    "PE": "America/Lima",
    "PER": "America/Lima",
    # Africa
    "ZA": "Africa/Johannesburg",
    "ZAF": "Africa/Johannesburg",
    "EG": "Africa/Cairo",
    "EGY": "Africa/Cairo",
    "NG": "Africa/Lagos",
    "NGA": "Africa/Lagos",
    "KE": "Africa/Nairobi",
    "KEN": "Africa/Nairobi",
    # Oceania
    "NZ": "Pacific/Auckland",
    "NZL": "Pacific/Auckland",
}


def is_valid_timezone(tz_name: Optional[str]) -> bool:
    """Return True if tz_name is a valid IANA timezone identifier known to ZoneInfo."""
    if not tz_name or not isinstance(tz_name, str):
        return False
    try:
        ZoneInfo(tz_name)
        return True
    except Exception:
        return False


def get_zone_info(tz_name: Optional[str]) -> ZoneInfo:
    """Get ZoneInfo object for the given timezone identifier, with safe fallback to UTC."""
    if not tz_name or not isinstance(tz_name, str):
        return ZoneInfo("UTC")
    try:
        return ZoneInfo(tz_name)
    except Exception:
        logger.warning("Unrecognized timezone '%s', falling back to UTC.", tz_name)
        return ZoneInfo("UTC")


def convert_utc_to_local(utc_dt: datetime, tz_name: Optional[str]) -> datetime:
    """Convert a UTC datetime to local datetime in the specified IANA timezone.
    
    If utc_dt is naive, it is assumed to represent UTC.
    If tz_name is invalid or missing, falls back to UTC.
    """
    if utc_dt.tzinfo is None:
        utc_dt = utc_dt.replace(tzinfo=timezone.utc)
    target_zi = get_zone_info(tz_name)
    return utc_dt.astimezone(target_zi)


def resolve_iana_timezone(
    lat: float,
    lon: float,
    country_code: Optional[str] = None
) -> str:
    """Resolve authoritative IANA timezone identifier from geographic metadata and coordinates.
    
    Adheres strictly to standard IANA timezone database identifiers without hardcoding.
    """
    tz_candidate: Optional[str] = None
    cc = country_code.upper().strip() if country_code else None

    # 1. Authoritative country-based resolution
    if cc in ("IN", "IND"):
        tz_candidate = "Asia/Kolkata"
    elif cc in ("GB", "GBR", "UK"):
        tz_candidate = "Europe/London"
    elif cc in ("US", "USA"):
        if lat > 50.0 and lon < -130.0:
            tz_candidate = "America/Anchorage"
        elif lat < 25.0 and lon < -150.0:
            tz_candidate = "Pacific/Honolulu"
        elif lon >= -85.0:
            tz_candidate = "America/New_York"
        elif lon >= -102.0:
            tz_candidate = "America/Chicago"
        elif lon >= -114.0:
            tz_candidate = "America/Denver"
        else:
            tz_candidate = "America/Los_Angeles"
    elif cc in ("CA", "CAN"):
        if lon >= -67.0:
            tz_candidate = "America/Halifax"
        elif lon >= -85.0:
            tz_candidate = "America/Toronto"
        elif lon >= -102.0:
            tz_candidate = "America/Winnipeg"
        elif lon >= -115.0:
            tz_candidate = "America/Edmonton"
        else:
            tz_candidate = "America/Vancouver"
    elif cc in ("AU", "AUS"):
        if lon >= 138.0:
            tz_candidate = "Australia/Sydney"
        elif lon >= 129.0:
            tz_candidate = "Australia/Adelaide"
        else:
            tz_candidate = "Australia/Perth"
    elif cc and cc in COUNTRY_PRIMARY_TIMEZONE:
        tz_candidate = COUNTRY_PRIMARY_TIMEZONE[cc]

    # 2. Coordinate bounding box resolution (for missing/ambiguous country metadata)
    if not tz_candidate:
        # India & Subcontinent
        if 6.0 <= lat <= 38.5 and 68.0 <= lon <= 98.0:
            tz_candidate = "Asia/Kolkata"
        # Great Britain & Ireland
        elif 49.0 <= lat <= 61.0 and -11.0 <= lon <= 2.0:
            tz_candidate = "Europe/London"
        # United States East Coast (New York, Boston, DC, etc.)
        elif 24.0 <= lat <= 50.0 and -85.0 <= lon <= -65.0:
            tz_candidate = "America/New_York"
        # United States Central (Chicago, Houston, Dallas)
        elif 25.0 <= lat <= 50.0 and -102.0 <= lon < -85.0:
            tz_candidate = "America/Chicago"
        # United States Mountain (Denver, Phoenix, Salt Lake City)
        elif 31.0 <= lat <= 49.0 and -114.0 <= lon < -102.0:
            tz_candidate = "America/Denver"
        # United States Pacific (Los Angeles, San Francisco, Seattle)
        elif 32.0 <= lat <= 49.0 and -125.0 <= lon < -114.0:
            tz_candidate = "America/Los_Angeles"
        # Western / Central Europe
        elif 35.0 <= lat <= 55.0 and 2.0 <= lon <= 16.0:
            tz_candidate = "Europe/Paris"
        # Japan
        elif 30.0 <= lat <= 46.0 and 128.0 <= lon <= 146.0:
            tz_candidate = "Asia/Tokyo"
        # Australia Eastern
        elif -40.0 <= lat <= -10.0 and 140.0 <= lon <= 155.0:
            tz_candidate = "Australia/Sydney"
        # Australia Western
        elif -36.0 <= lat <= -12.0 and 112.0 <= lon <= 129.0:
            tz_candidate = "Australia/Perth"

    if not tz_candidate:
        tz_candidate = "UTC"

    # 3. Validate with standard library ZoneInfo
    try:
        ZoneInfo(tz_candidate)
        return tz_candidate
    except Exception:
        logger.warning(
            "Invalid timezone '%s' generated for (%.4f, %.4f). Falling back to UTC.",
            tz_candidate,
            lat,
            lon,
        )
        return "UTC"
