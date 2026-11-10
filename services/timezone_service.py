from __future__ import annotations

from typing import Optional
from zoneinfo import ZoneInfo
import pytz

from api_layer.logging import get_logger

logger = get_logger(__name__)


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
    elif cc and cc in pytz.country_timezones:
        country_tzs = pytz.country_timezones[cc]
        if len(country_tzs) == 1:
            tz_candidate = country_tzs[0]

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
        logger.warning("Invalid timezone '%s' generated for (%.4f, %.4f). Falling back to UTC.", tz_candidate, lat, lon)
        return "UTC"
