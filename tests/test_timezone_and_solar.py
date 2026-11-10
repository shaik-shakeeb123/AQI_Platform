from __future__ import annotations

import time
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo
import pytest

from data_sync.clients.nominatim_client import GeocodingResult
from services.timezone_service import resolve_iana_timezone
from services.weather_provider_manager import (
    WeatherProviderManager,
    clear_shared_weather_cache,
)
from services.weather_service import (
    WeatherService,
    clear_weather_service_cache,
)
from data_sync.models.weather_models import NormalizedCurrentWeather


@pytest.fixture(autouse=True)
def clean_caches():
    clear_shared_weather_cache()
    clear_weather_service_cache()
    yield
    clear_shared_weather_cache()
    clear_weather_service_cache()


# ── 1. Backend IANA Timezone Resolution Tests ─────────────────────────────────

def test_resolve_iana_timezone_target_cities():
    """Verify IANA timezone resolution for all mandatory target cities."""
    # Madanapalle, India
    assert resolve_iana_timezone(13.6268, 78.5040, "IN") == "Asia/Kolkata"
    # Mumbai, India
    assert resolve_iana_timezone(19.0760, 72.8777, "IN") == "Asia/Kolkata"
    # Delhi, India
    assert resolve_iana_timezone(28.6139, 77.2090, "IN") == "Asia/Kolkata"
    # London, UK
    assert resolve_iana_timezone(51.5074, -0.1278, "GB") == "Europe/London"
    # New York, USA
    assert resolve_iana_timezone(40.7128, -74.0060, "US") == "America/New_York"


def test_resolve_iana_timezone_coordinate_fallback_without_country_code():
    """Verify coordinate-only fallback when country_code is missing or None."""
    # Madanapalle coordinates alone
    assert resolve_iana_timezone(13.6268, 78.5040, None) == "Asia/Kolkata"
    # Delhi coordinates alone
    assert resolve_iana_timezone(28.6139, 77.2090, None) == "Asia/Kolkata"
    # London coordinates alone
    assert resolve_iana_timezone(51.5074, -0.1278, None) == "Europe/London"
    # New York coordinates alone
    assert resolve_iana_timezone(40.7128, -74.0060, None) == "America/New_York"
    # Unknown ocean coordinates fallback to UTC
    assert resolve_iana_timezone(0.0, 0.0, None) == "UTC"


def test_resolve_iana_timezone_returns_valid_zoneinfo():
    """Verify every resolved timezone can be loaded by Python standard library ZoneInfo."""
    test_coords = [
        (13.6268, 78.5040, "IN"),
        (51.5074, -0.1278, "GB"),
        (40.7128, -74.0060, "US"),
        (48.8566, 2.3522, "FR"),
        (35.6762, 139.6503, "JP"),
        (-33.8688, 151.2093, "AU"),
    ]
    for lat, lon, cc in test_coords:
        tz_name = resolve_iana_timezone(lat, lon, cc)
        zi = ZoneInfo(tz_name)
        assert zi is not None
        assert zi.key == tz_name


# ── 2. Timestamp Semantics & Solar Conversion Tests ───────────────────────────

def test_solar_timestamp_utc_semantics_and_conversion():
    """Verify that sunrise/sunset are preserved as UTC instants and convert accurately to IST.
    
    Target requirement:
      For Madanapalle:
        00:43:31 UTC -> 06:13:31 IST (approximately 06:13 AM)
        12:16:42 UTC -> 17:46:42 IST (approximately 05:46 PM)
    """
    sr_utc = datetime.fromisoformat("2026-11-10T00:43:31+00:00")
    ss_utc = datetime.fromisoformat("2026-11-10T12:16:42+00:00")

    # Backend preserves exact UTC instant
    assert sr_utc.tzinfo == timezone.utc
    assert ss_utc.tzinfo == timezone.utc

    # Convert to Asia/Kolkata
    ist_tz = ZoneInfo("Asia/Kolkata")
    sr_ist = sr_utc.astimezone(ist_tz)
    ss_ist = ss_utc.astimezone(ist_tz)

    assert sr_ist.hour == 6
    assert sr_ist.minute == 13
    assert ss_ist.hour == 17  # 5 PM
    assert ss_ist.minute == 46

    # Formatted 12-hour strings
    sr_str = sr_ist.strftime("%I:%M %p")
    ss_str = ss_ist.strftime("%I:%M %p")
    assert sr_str == "06:13 AM"
    assert ss_str == "05:46 PM"


def test_daylight_saving_transitions_handling():
    """Verify that IANA timezone rules handle daylight-saving transitions automatically."""
    london_tz = ZoneInfo("Europe/London")
    ny_tz = ZoneInfo("America/New_York")

    # Summer solstice (BST = UTC+1, EDT = UTC-4)
    summer_dt = datetime.fromisoformat("2026-07-01T04:45:00+00:00")
    assert summer_dt.astimezone(london_tz).strftime("%I:%M %p") == "05:45 AM"
    assert summer_dt.astimezone(ny_tz).strftime("%I:%M %p") == "12:45 AM"

    # Winter (GMT = UTC+0, EST = UTC-5)
    winter_dt = datetime.fromisoformat("2026-12-01T07:45:00+00:00")
    assert winter_dt.astimezone(london_tz).strftime("%I:%M %p") == "07:45 AM"
    assert winter_dt.astimezone(ny_tz).strftime("%I:%M %p") == "02:45 AM"


# ── 3. WeatherService End-to-End Timezone Resolution ─────────────────────────

@pytest.mark.asyncio
async def test_weather_service_resolves_city_iana_timezone():
    """Verify WeatherService populates the correct IANA timezone on WeatherResponse."""
    mock_geo_madanapalle = GeocodingResult(
        latitude=13.6268,
        longitude=78.5040,
        country="India",
        country_code="IN",
    )

    mock_weather = NormalizedCurrentWeather(
        temperature=21.0,
        humidity=70.0,
        wind_speed=8.0,
        sunrise="2026-11-10T00:43:31+00:00",
        sunset="2026-11-10T12:16:42+00:00",
        sunrise_timestamp=1794271411,
        sunset_timestamp=1794313002,
        provider="MET Norway",
        source="MET_NORWAY",
        attribution="Data from MET Norway (api.met.no)",
        is_available=True,
    )

    manager = WeatherProviderManager()
    manager.get_current_weather = AsyncMock(return_value=mock_weather)
    service = WeatherService(provider_manager=manager)

    with patch("data_sync.clients.nominatim_client.NominatimGeocoderClient.geocode_address_with_details", new_callable=AsyncMock, return_value=mock_geo_madanapalle):
        response = await service.get_weather("Madanapalle")

        # Crucial assertion: Must NOT be "UTC"!
        assert response.timezone == "Asia/Kolkata"
        assert response.city == "Madanapalle"
        assert response.sunrise == "2026-11-10T00:43:31+00:00"
        assert response.sunset == "2026-11-10T12:16:42+00:00"
        assert response.sunrise_timestamp == 1794271411
        assert response.sunset_timestamp == 1794313002


@pytest.mark.asyncio
async def test_weather_service_international_timezones():
    """Verify WeatherService assigns appropriate international timezones for London and New York."""
    service = WeatherService()

    # London
    mock_geo_london = GeocodingResult(
        latitude=51.5074,
        longitude=-0.1278,
        country="United Kingdom",
        country_code="GB",
    )
    mock_weather = NormalizedCurrentWeather(
        temperature=12.0,
        sunrise="2026-11-10T07:15:00+00:00",
        sunset="2026-11-10T16:20:00+00:00",
        provider="MET Norway",
        is_available=True,
    )
    service.provider_manager.get_current_weather = AsyncMock(return_value=mock_weather)

    with patch("data_sync.clients.nominatim_client.NominatimGeocoderClient.geocode_address_with_details", new_callable=AsyncMock, return_value=mock_geo_london):
        resp_london = await service.get_weather("London")
        assert resp_london.timezone == "Europe/London"

    # New York
    mock_geo_ny = GeocodingResult(
        latitude=40.7128,
        longitude=-74.0060,
        country="United States",
        country_code="US",
    )
    with patch("data_sync.clients.nominatim_client.NominatimGeocoderClient.geocode_address_with_details", new_callable=AsyncMock, return_value=mock_geo_ny):
        resp_ny = await service.get_weather("New York")
        assert resp_ny.timezone == "America/New_York"
