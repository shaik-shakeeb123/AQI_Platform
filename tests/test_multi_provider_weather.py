from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch, MagicMock
import httpx
import pytest
import respx

from api_layer.exceptions import ExternalAPIException
from data_sync.clients.base_weather_provider import BaseWeatherProvider
from data_sync.clients.met_norway_client import (
    MetNorwayClient,
    clear_met_norway_state,
)
from data_sync.clients.met_norway_symbol_mapping import decode_met_norway_symbol
from data_sync.clients.openmeteo_provider import OpenMeteoProvider
from data_sync.clients.openmeteo_weather_client import (
    OpenMeteoWeatherClient,
    clear_weather_cache as clear_openmeteo_cache,
    set_cooldown as set_openmeteo_cooldown,
)
from data_sync.data_processor import DataProcessor
from data_sync.models.weather_models import (
    NormalizedCurrentWeather,
    NormalizedHourlyForecast,
    calculate_apparent_temperature,
    calculate_solar_times,
)
from services.weather_provider_manager import (
    WeatherProviderManager,
    clear_shared_weather_cache,
    get_manager_metrics,
    reset_manager_metrics,
)
from services.weather_service import (
    WeatherService,
    clear_weather_service_cache,
)


@pytest.fixture(autouse=True)
def clean_all_weather_state():
    """Reset all provider, manager, and service caches and cooldowns before/after every test."""
    clear_shared_weather_cache()
    clear_weather_service_cache()
    clear_met_norway_state()
    clear_openmeteo_cache()
    yield
    clear_shared_weather_cache()
    clear_weather_service_cache()
    clear_met_norway_state()
    clear_openmeteo_cache()


# ── 1. Normalized Models & Solar / Apparent Temp Tests ─────────────────────────

def test_apparent_temperature_calculation():
    """Verify Steadman apparent temperature calculation."""
    # 25C, 60% humidity, 2 m/s wind
    at = calculate_apparent_temperature(25.0, 60.0, wind_speed_ms=2.0)
    assert 24.0 <= at <= 28.0

    # Hot and humid: 35C, 80% humidity
    at_hot = calculate_apparent_temperature(35.0, 80.0, wind_speed_ms=1.0)
    assert at_hot > 38.0


def test_noaa_solar_times_calculation():
    """Verify NOAA astronomical sunrise/sunset calculation."""
    # Delhi, India (28.61, 77.21)
    test_dt = datetime(2026, 6, 21, 12, 0, tzinfo=timezone.utc)  # Summer solstice
    sr, ss = calculate_solar_times(28.6139, 77.2090, test_dt)
    assert sr is not None and ss is not None
    assert sr < ss
    # Delhi sunrise around 05:20-05:30 IST (23:50-00:00 UTC)
    assert sr.hour in (23, 0)
    assert ss.hour in (13, 14)


def test_decode_met_norway_symbol():
    """Verify decoding of MET Norway symbol codes with day/night variants."""
    cond, desc, icon, wmo = decode_met_norway_symbol("clearsky_day", is_daytime=True)
    assert cond == "Clear"
    assert "clear" in desc.lower()
    assert icon == "01d"
    assert wmo == 0

    cond, desc, icon, wmo = decode_met_norway_symbol("clearsky_night", is_daytime=False)
    assert cond == "Clear"
    assert icon == "01n"

    cond, desc, icon, wmo = decode_met_norway_symbol("heavyrainshowers_day", is_daytime=True)
    assert cond == "Rain"
    assert icon == "09d"

    cond, desc, icon, wmo = decode_met_norway_symbol("fog", is_daytime=True)
    assert cond == "Fog"
    assert icon == "50d"


def test_normalized_current_weather_legacy_dict():
    """Verify NormalizedCurrentWeather exports legacy dictionary compatible with merge_weather."""
    now = datetime.now(timezone.utc)
    weather = NormalizedCurrentWeather(
        temperature=30.5,
        feels_like=33.2,
        humidity=70.0,
        wind_speed=15.0,
        wind_direction=180.0,
        pressure=1012.0,
        precipitation=0.5,
        weather_code=1,
        condition="Clear",
        recorded_at=now,
        provider="MET Norway",
        source="MET_NORWAY",
    )
    legacy = weather.to_legacy_dict()
    assert legacy["current"]["temperature_2m"] == 30.5
    assert legacy["current"]["relative_humidity_2m"] == 70.0
    assert legacy["current"]["wind_speed_10m"] == 15.0
    assert legacy["provider"] == "MET Norway"

    # Verify DataProcessor.merge_weather handles it seamlessly
    pollutants = {"temperature": None, "humidity": None}
    merged = DataProcessor.merge_weather(pollutants, legacy)
    assert merged["temperature"] == 30.5
    assert merged["humidity"] == 70.0
    assert merged["wind_speed"] == 15.0


# ── 2. MET Norway Client Tests ────────────────────────────────────────────────

@pytest.mark.asyncio
@respx.mock
async def test_met_norway_client_success():
    """Verify MET Norway client fetches and parses Locationforecast 2.0 GeoJSON."""
    lat, lon = 28.6139, 77.2090
    geojson_mock = {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [lon, lat, 100]},
        "properties": {
            "meta": {"units": {"air_temperature": "celsius", "wind_speed": "m/s"}},
            "timeseries": [
                {
                    "time": "2026-11-10T12:00:00Z",
                    "data": {
                        "instant": {
                            "details": {
                                "air_temperature": 24.5,
                                "relative_humidity": 50.0,
                                "air_pressure_at_sea_level": 1013.2,
                                "wind_speed": 3.0,  # 3.0 m/s -> 10.8 km/h
                                "wind_from_direction": 270.0,
                                "cloud_area_fraction": 10.0,
                            }
                        },
                        "next_1_hours": {
                            "summary": {"symbol_code": "clearsky_day"},
                            "details": {"precipitation_amount": 0.0},
                        },
                    },
                },
                {
                    "time": "2026-11-10T13:00:00Z",
                    "data": {
                        "instant": {
                            "details": {
                                "air_temperature": 23.8,
                                "relative_humidity": 55.0,
                                "air_pressure_at_sea_level": 1013.5,
                                "wind_speed": 2.5,
                                "wind_from_direction": 260.0,
                                "cloud_area_fraction": 20.0,
                            }
                        },
                        "next_1_hours": {
                            "summary": {"symbol_code": "partlycloudy_day"},
                            "details": {"precipitation_amount": 0.1},
                        },
                    },
                },
            ],
        },
    }

    url = "https://api.met.no/weatherapi/locationforecast/2.0/compact?lat=28.6139&lon=77.2090"
    respx.get(url).mock(return_value=httpx.Response(200, json=geojson_mock, headers={"Last-Modified": "Tue, 10 Nov 2026 12:00:00 GMT"}))

    client = MetNorwayClient()
    current = await client.fetch_current_weather(lat, lon)

    assert current.provider == "MET Norway"
    assert current.temperature == 24.5
    assert current.humidity == 50.0
    assert current.wind_speed == 10.8  # 3.0 * 3.6
    assert current.condition == "Clear"
    assert current.attribution == "Data from MET Norway (api.met.no)"
    assert current.is_available is True

    # Test hourly forecast
    hourly = await client.fetch_hourly_forecast(lat, lon, hours=2)
    assert len(hourly) == 2
    assert hourly[0].temperature == 24.5
    assert hourly[1].temperature == 23.8


@pytest.mark.asyncio
@respx.mock
async def test_met_norway_client_304_not_modified():
    """Verify MET Norway conditional 304 response returns cached payload without re-parsing failure."""
    lat, lon = 28.6139, 77.2090
    geojson_mock = {
        "properties": {
            "timeseries": [
                {
                    "time": "2026-11-10T12:00:00Z",
                    "data": {
                        "instant": {"details": {"air_temperature": 22.0, "relative_humidity": 45.0, "wind_speed": 2.0}},
                        "next_1_hours": {"summary": {"symbol_code": "clearsky_day"}},
                    },
                }
            ]
        }
    }
    url = "https://api.met.no/weatherapi/locationforecast/2.0/compact?lat=28.6139&lon=77.2090"
    route = respx.get(url)
    route.side_effect = [
        httpx.Response(200, json=geojson_mock, headers={"Last-Modified": "Tue, 10 Nov 2026 12:00:00 GMT"}),
        httpx.Response(304, headers={"Last-Modified": "Tue, 10 Nov 2026 12:00:00 GMT"}),
    ]

    client = MetNorwayClient()
    res1 = await client.fetch_current_weather(lat, lon)
    assert res1.temperature == 22.0

    # Second call should handle 304 and re-use raw cached payload
    res2 = await client.fetch_current_weather(lat, lon)
    assert res2.temperature == 22.0
    metrics = client.get_metrics()
    assert metrics["cache_304_hits"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_met_norway_client_429_cooldown():
    """Verify MET Norway 429 engages cooldown and parses Retry-After header."""
    lat, lon = 28.6139, 77.2090
    url = "https://api.met.no/weatherapi/locationforecast/2.0/compact?lat=28.6139&lon=77.2090"
    respx.get(url).mock(return_value=httpx.Response(429, headers={"Retry-After": "120"}))

    client = MetNorwayClient()
    with pytest.raises(ExternalAPIException) as exc_info:
        await client.fetch_current_weather(lat, lon)

    assert exc_info.value.upstream_status == 429
    assert client.is_rate_limited() is True
    assert client.get_cooldown_remaining() > 100.0

    # Subsequent request is immediately suppressed by client
    with pytest.raises(ExternalAPIException) as exc_info2:
        await client.fetch_current_weather(lat, lon)
    assert "MET_NORWAY_COOLDOWN_ACTIVE" in exc_info2.value.error_code


@pytest.mark.asyncio
@respx.mock
async def test_met_norway_client_transient_5xx_retry():
    """Verify MET Norway client retries on transient 502/503 errors."""
    lat, lon = 28.6139, 77.2090
    geojson_mock = {
        "properties": {
            "timeseries": [
                {
                    "time": "2026-11-10T12:00:00Z",
                    "data": {
                        "instant": {"details": {"air_temperature": 26.0, "relative_humidity": 40.0, "wind_speed": 1.0}},
                        "next_1_hours": {"summary": {"symbol_code": "clearsky_day"}},
                    },
                }
            ]
        }
    }
    url = "https://api.met.no/weatherapi/locationforecast/2.0/compact?lat=28.6139&lon=77.2090"
    route = respx.get(url)
    route.side_effect = [
        httpx.Response(502),
        httpx.Response(200, json=geojson_mock),
    ]

    with patch("asyncio.sleep", new_callable=AsyncMock):
        client = MetNorwayClient()
        current = await client.fetch_current_weather(lat, lon)
        assert current.temperature == 26.0


# ── 3. Weather Provider Manager Multi-Provider & Fallback Tests ───────────────

class MockSuccessProvider(BaseWeatherProvider):
    def __init__(self, name: str, temp: float = 25.0):
        self.name = name
        self.temp = temp
        self._cooldown = 0.0

    def get_provider_name(self) -> str:
        return self.name

    def get_attribution(self) -> str:
        return f"Data from {self.name}"

    def is_rate_limited(self) -> bool:
        return time.monotonic() < self._cooldown

    def get_cooldown_remaining(self) -> float:
        return max(0.0, self._cooldown - time.monotonic())

    def set_cooldown(self, seconds: float, reason: str = "") -> None:
        self._cooldown = time.monotonic() + seconds

    def get_metrics(self) -> dict:
        return {}

    def reset_metrics(self) -> None:
        pass

    async def fetch_current_weather(self, lat: float, lon: float) -> NormalizedCurrentWeather:
        await asyncio.sleep(0.01)  # Simulate non-zero upstream network latency
        return NormalizedCurrentWeather(
            temperature=self.temp,
            feels_like=self.temp + 1.0,
            humidity=50.0,
            wind_speed=10.0,
            provider=self.name,
            source=self.name.upper().replace(" ", "_"),
            attribution=self.get_attribution(),
            is_available=True,
        )

    async def fetch_hourly_forecast(self, lat: float, lon: float, hours: int = 48) -> list:
        now = datetime.now(timezone.utc)
        return [
            NormalizedHourlyForecast(
                timestamp=now + timedelta(hours=i),
                temperature=self.temp + i,
                provider=self.name,
            )
            for i in range(hours)
        ]


class MockFailingProvider(BaseWeatherProvider):
    def __init__(self, name: str, status_code: int = 502):
        self.name = name
        self.status_code = status_code
        self._cooldown = 0.0

    def get_provider_name(self) -> str:
        return self.name

    def get_attribution(self) -> str:
        return f"Data from {self.name}"

    def is_rate_limited(self) -> bool:
        return time.monotonic() < self._cooldown

    def get_cooldown_remaining(self) -> float:
        return max(0.0, self._cooldown - time.monotonic())

    def set_cooldown(self, seconds: float, reason: str = "") -> None:
        self._cooldown = time.monotonic() + seconds

    def get_metrics(self) -> dict:
        return {}

    def reset_metrics(self) -> None:
        pass

    async def fetch_current_weather(self, lat: float, lon: float) -> NormalizedCurrentWeather:
        raise ExternalAPIException(
            detail=f"{self.name} failed with status {self.status_code}",
            error_code=f"{self.name.upper()}_ERROR",
            status_code=502,
            upstream_status=self.status_code,
        )

    async def fetch_hourly_forecast(self, lat: float, lon: float, hours: int = 48) -> list:
        raise ExternalAPIException(
            detail=f"{self.name} hourly failed",
            error_code=f"{self.name.upper()}_ERROR",
            status_code=502,
            upstream_status=self.status_code,
        )


@pytest.mark.asyncio
async def test_provider_manager_primary_success():
    """Verify provider manager returns primary provider data when healthy."""
    primary = MockSuccessProvider("MET Norway", temp=22.5)
    secondary = MockSuccessProvider("Open-Meteo", temp=28.0)

    manager = WeatherProviderManager(primary_provider=primary, secondary_provider=secondary)
    res = await manager.get_current_weather(12.97, 77.59)

    assert res.provider == "MET Norway"
    assert res.temperature == 22.5
    assert res.is_available is True

    metrics = get_manager_metrics()
    assert metrics["primary_successes"] == 1
    assert metrics["secondary_requests"] == 0


@pytest.mark.asyncio
async def test_provider_manager_primary_failure_secondary_success():
    """Verify automatic failover to secondary provider when primary fails."""
    primary = MockFailingProvider("MET Norway", status_code=502)
    secondary = MockSuccessProvider("Open-Meteo", temp=29.0)

    manager = WeatherProviderManager(primary_provider=primary, secondary_provider=secondary)
    res = await manager.get_current_weather(12.97, 77.59)

    assert res.provider == "Open-Meteo"
    assert res.temperature == 29.0
    assert res.is_available is True

    metrics = get_manager_metrics()
    assert metrics["primary_failures"] == 1
    assert metrics["fallback_events"] == 1
    assert metrics["secondary_successes"] == 1


@pytest.mark.asyncio
async def test_provider_manager_independent_cooldowns():
    """Verify primary cooldown bypasses primary directly without impacting secondary."""
    primary = MockSuccessProvider("MET Norway", temp=22.0)
    primary.set_cooldown(3600.0)  # Primary in active cooldown

    secondary = MockSuccessProvider("Open-Meteo", temp=31.0)  # Secondary healthy

    manager = WeatherProviderManager(primary_provider=primary, secondary_provider=secondary)
    res = await manager.get_current_weather(17.38, 78.48)

    # Secondary should be called immediately without waiting on primary
    assert res.provider == "Open-Meteo"
    assert res.temperature == 31.0

    metrics = get_manager_metrics()
    assert metrics["primary_requests"] == 0  # Bypassed
    assert metrics["secondary_requests"] == 1


@pytest.mark.asyncio
async def test_provider_manager_all_providers_down_stale_cache():
    """Verify that when all upstream providers fail, stale cache is served with STALE_CACHE."""
    primary = MockSuccessProvider("MET Norway", temp=27.0)
    secondary = MockSuccessProvider("Open-Meteo", temp=27.0)

    manager = WeatherProviderManager(primary_provider=primary, secondary_provider=secondary)
    lat, lon = 13.08, 80.27

    # 1. Warm cache
    fresh = await manager.get_current_weather(lat, lon)
    assert fresh.temperature == 27.0

    # 2. Both providers fail and fresh TTL (10m) expires, but stale TTL (1h) is active
    primary_fail = MockFailingProvider("MET Norway", status_code=502)
    secondary_fail = MockFailingProvider("Open-Meteo", status_code=502)
    manager.primary = primary_fail
    manager.secondary = secondary_fail

    real_mono = time.monotonic
    with patch("time.monotonic", side_effect=lambda: real_mono() + 900.0):  # +15 minutes
        stale_res = await manager.get_current_weather(lat, lon)
        assert stale_res.source == "STALE_CACHE"
        assert stale_res.temperature == 27.0
        assert stale_res.is_available is True

    metrics = get_manager_metrics()
    assert metrics["stale_cache_hits"] == 1


@pytest.mark.asyncio
async def test_provider_manager_all_providers_down_controlled_unavailable():
    """Verify controlled UNAVAILABLE response with HTTP 200 when all providers down and no cache."""
    primary = MockFailingProvider("MET Norway", status_code=502)
    secondary = MockFailingProvider("Open-Meteo", status_code=502)

    manager = WeatherProviderManager(primary_provider=primary, secondary_provider=secondary)
    res = await manager.get_current_weather(15.82, 78.03)

    assert res.is_available is False
    assert res.source == "UNAVAILABLE"
    assert res.condition == "Unavailable"
    assert res.temperature is None
    assert res.cooldown_remaining_seconds is not None

    metrics = get_manager_metrics()
    assert metrics["unavailable_responses"] == 1


@pytest.mark.asyncio
async def test_concurrent_request_coalescing():
    """Verify multiple concurrent requests for the same coordinates execute only 1 upstream call."""
    primary = MockSuccessProvider("MET Norway", temp=25.0)
    fetch_spy = AsyncMock(wraps=primary.fetch_current_weather)
    primary.fetch_current_weather = fetch_spy

    manager = WeatherProviderManager(primary_provider=primary)

    # Fire 5 concurrent identical requests
    tasks = [
        asyncio.create_task(manager.get_current_weather(28.61, 77.20))
        for _ in range(5)
    ]
    results = await asyncio.gather(*tasks)

    for r in results:
        assert r.temperature == 25.0

    # Exactly 1 upstream call occurred due to asyncio lock coalescing
    assert fetch_spy.await_count == 1
    metrics = get_manager_metrics()
    assert metrics["coalesced_requests"] == 4


# ── 4. WeatherService Integration & API Response Compatibility ────────────────

@pytest.mark.asyncio
async def test_weather_service_get_weather_with_manager():
    """Verify WeatherService geocodes and returns compliant WeatherResponse."""
    from data_sync.clients.nominatim_client import GeocodingResult

    mock_geo = GeocodingResult(
        latitude=28.61,
        longitude=77.20,
        country="India",
        country_code="IN",
    )
    primary = MockSuccessProvider("MET Norway", temp=26.4)
    manager = WeatherProviderManager(primary_provider=primary)
    service = WeatherService(provider_manager=manager)

    with patch("data_sync.clients.nominatim_client.NominatimGeocoderClient.geocode_address_with_details", new_callable=AsyncMock, return_value=mock_geo):
        response = await service.get_weather("Delhi")

        assert response.city == "Delhi"
        assert response.temperature == 26.4
        assert response.provider == "MET Norway"
        assert response.source == "MET_NORWAY"
        assert response.attribution == "Data from MET Norway"
        assert response.is_available is True


@pytest.mark.asyncio
async def test_weather_service_fetch_hourly_forecast():
    """Verify WeatherService.fetch_hourly_forecast formats dictionary for SafeWindowService."""
    primary = MockSuccessProvider("MET Norway", temp=20.0)
    manager = WeatherProviderManager(primary_provider=primary)

    with patch("services.weather_service.WeatherProviderManager", return_value=manager):
        forecast_map = await WeatherService.fetch_hourly_forecast(28.61, 77.20)
        assert len(forecast_map) > 0
        first_key = list(forecast_map.keys())[0]
        assert len(first_key) == 4  # (year, month, day, hour)
        assert "temperature" in forecast_map[first_key]
        assert "humidity" in forecast_map[first_key]
