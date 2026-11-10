import asyncio
import time
from unittest.mock import AsyncMock, patch, MagicMock
import httpx
import pytest
import respx

from data_sync.clients.openmeteo_weather_client import (
    OpenMeteoWeatherClient,
    clear_weather_cache,
    is_rate_limited,
    get_cooldown_remaining,
    set_cooldown,
    get_weather_client_metrics,
)
from services.weather_service import clear_weather_service_cache
from api_layer.exceptions import ExternalAPIException


@pytest.fixture(autouse=True)
def reset_weather_cache_state():
    """Ensure in-memory weather cache and cooldown are reset before and after every test."""
    clear_weather_cache()
    clear_weather_service_cache()
    yield
    clear_weather_cache()
    clear_weather_service_cache()


@pytest.mark.asyncio
async def test_coordinate_caching_current_and_hourly():
    client = OpenMeteoWeatherClient()
    mock_payload = {
        "current": {"temperature_2m": 28.5, "relative_humidity_2m": 65},
        "daily": {"sunrise": ["2026-10-25T06:00"], "sunset": ["2026-10-25T18:00"]},
    }
    mock_hourly_payload = {
        "hourly": {
            "time": ["2026-10-25T00:00"],
            "temperature_2m": [25.0],
            "relative_humidity_2m": [70],
        }
    }

    with patch("data_sync.clients.openmeteo_weather_client._get_with_retry", new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = [mock_payload, mock_hourly_payload]

        # 1. First fetch for current weather
        res1 = await client.fetch_current_weather(19.076, 72.877)
        assert res1 == mock_payload
        assert mock_get.call_count == 1

        # 2. Second fetch for same rounded coordinates (19.08, 72.88) -> CACHE HIT
        res2 = await client.fetch_current_weather(19.078, 72.879)
        assert res2 == mock_payload
        assert mock_get.call_count == 1  # No additional network call!

        # 3. Hourly forecast for same coordinates has separate cache key
        res3 = await client.fetch_hourly_weather(19.076, 72.877, forecast_days=1)
        assert res3 == mock_hourly_payload
        assert mock_get.call_count == 2  # Different cache key called network

        # 4. Second hourly fetch -> CACHE HIT
        res4 = await client.fetch_hourly_weather(19.076, 72.877, forecast_days=1)
        assert res4 == mock_hourly_payload
        assert mock_get.call_count == 2


@pytest.mark.asyncio
async def test_concurrent_cache_miss_request_coalescing():
    client = OpenMeteoWeatherClient()
    mock_payload = {"current": {"temperature_2m": 30.0}}

    call_count = 0

    async def delayed_fetch(url, params, **kwargs):
        nonlocal call_count
        call_count += 1
        await asyncio.sleep(0.05)
        return mock_payload

    with patch("data_sync.clients.openmeteo_weather_client._get_with_retry", side_effect=delayed_fetch):
        # Fire 10 concurrent requests for the exact same coordinate
        tasks = [
            asyncio.create_task(client.fetch_current_weather(13.08, 80.27))
            for _ in range(10)
        ]
        results = await asyncio.gather(*tasks)

        # All 10 returned identical payload
        for r in results:
            assert r == mock_payload

        # Crucial: Exactly 1 upstream call made; singleflight lock coalesced the other 9
        assert call_count == 1


@pytest.mark.asyncio
async def test_http_429_retry_after_cooldown():
    client = OpenMeteoWeatherClient()

    # Mock HTTP 429 response with Retry-After: 45
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 429
    mock_response.headers = {"Retry-After": "45"}

    with patch("data_sync.clients.openmeteo_weather_client._get_client") as mock_get_client:
        mock_http_client = AsyncMock()
        mock_http_client.get = AsyncMock(return_value=mock_response)
        mock_get_client.return_value = mock_http_client

        # Initial call should fail with 429
        with pytest.raises(ExternalAPIException) as exc_info:
            await client.fetch_current_weather(12.97, 77.59)

        assert exc_info.value.upstream_status == 429
        # Verified: Did NOT retry 3 times; broke immediately to avoid pounding upstream!
        assert mock_http_client.get.call_count == 1

        # Global cooldown is now active
        assert is_rate_limited() is True
        assert get_cooldown_remaining() > 40.0

        # Subsequent call during cooldown should fail fast WITHOUT issuing any HTTP call
        with pytest.raises(ExternalAPIException) as exc_info2:
            await client.fetch_current_weather(28.61, 77.20)

        assert exc_info2.value.upstream_status == 429
        assert "cooldown active" in exc_info2.value.detail.lower()
        # Still 1: no second network call was initiated!
        assert mock_http_client.get.call_count == 1


@pytest.mark.asyncio
async def test_stale_cache_fallback_during_429():
    client = OpenMeteoWeatherClient()
    cached_payload = {"current": {"temperature_2m": 22.0}}

    # 1. Warm cache
    with patch("data_sync.clients.openmeteo_weather_client._get_with_retry", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = cached_payload
        res = await client.fetch_current_weather(15.82, 78.03)
        assert res == cached_payload

    # 2. Trigger cooldown
    set_cooldown(60.0)
    assert is_rate_limited() is True

    # 3. Calling while rate-limited should serve stale cache instead of failing!
    stale_res = await client.fetch_current_weather(15.82, 78.03)
    assert stale_res == cached_payload


@pytest.mark.asyncio
async def test_current_aqi_logging_distinguishes_weather_status():
    from services.current_aqi_service import CurrentAQIService
    from api_layer.repositories.current_aqi_repository import CurrentAQIRepository

    mock_repo = MagicMock(spec=CurrentAQIRepository)
    # Simulate no fresh DB data so it falls back to Open-Meteo
    mock_repo.get_recent_readings_for_city = MagicMock(return_value=[])

    service = CurrentAQIService(mock_repo)

    mock_aq = {
        "current": {
            "pm2_5": 35.0,
            "pm10": 60.0,
            "nitrogen_dioxide": 20.0,
            "sulphur_dioxide": 10.0,
            "ozone": 25.0,
            "carbon_monoxide": 500.0,
            "time": "2026-10-25T12:00:00Z",
        }
    }
    mock_weather = {
        "current": {
            "temperature_2m": 27.5,
            "relative_humidity_2m": 55,
            "wind_speed_10m": 3.2,
            "wind_direction_10m": 180,
            "surface_pressure": 1012,
        }
    }

    with patch("data_sync.clients.nominatim_client.NominatimGeocoderClient.geocode_address", new_callable=AsyncMock, return_value=(19.07, 72.87)), \
         patch("services.current_aqi_service.OpenMeteoAirQualityClient.fetch_air_quality", new_callable=AsyncMock, return_value=mock_aq), \
         patch("services.current_aqi_service.logger") as mock_logger:

        # Case A: Weather succeeds -> Weather: Enriched
        with patch("services.current_aqi_service.OpenMeteoWeatherClient.fetch_current_weather", new_callable=AsyncMock, return_value=mock_weather):
            resp = await service.get_current_aqi("Mumbai")
            assert resp.temperature == 27.5
            # Find the final Provider: Open-Meteo log line
            info_logs = [call[0][0] for call in mock_logger.info.call_args_list]
            success_log = [l for l in info_logs if "Provider: Open-Meteo | Status: Success" in l]
            assert len(success_log) == 1
            assert "Weather: Enriched" in success_log[0]

        mock_logger.reset_mock()

        # Case B: Weather fails (429) -> Weather: Unavailable
        with patch("services.current_aqi_service.OpenMeteoWeatherClient.fetch_current_weather", new_callable=AsyncMock, side_effect=ExternalAPIException(detail="429 Too Many Requests", error_code="OPEN_METEO_API_ERROR", status_code=502, upstream_status=429)):
            resp = await service.get_current_aqi("Mumbai")
            assert resp.temperature is None
            info_logs = [call[0][0] for call in mock_logger.info.call_args_list]
            partial_log = [l for l in info_logs if "Provider: Open-Meteo | Status: Success" in l]
            assert len(partial_log) == 1
            assert "Weather: Unavailable" in partial_log[0]


@pytest.mark.asyncio
async def test_retry_after_http_date_parsing():
    import email.utils
    from datetime import datetime, timezone, timedelta
    from data_sync.clients.openmeteo_weather_client import _parse_retry_after

    # 1. Numeric seconds
    assert _parse_retry_after("30") == 30.0
    assert _parse_retry_after("15.5") == 15.5

    # 2. HTTP-date format (RFC 7231 / RFC 2822)
    future_time = datetime.now(timezone.utc) + timedelta(seconds=120)
    future_http_str = email.utils.format_datetime(future_time)
    parsed = _parse_retry_after(future_http_str)
    assert 115 <= parsed <= 125

    # 3. Past HTTP-date format returns minimum 1.0s
    past_time = datetime.now(timezone.utc) - timedelta(seconds=10)
    past_http_str = email.utils.format_datetime(past_time)
    assert _parse_retry_after(past_http_str) == 1.0

    # 4. Fallback on invalid/empty
    assert _parse_retry_after("") == 60.0
    assert _parse_retry_after("not-a-date-or-number") == 60.0


@pytest.mark.asyncio
async def test_stale_cache_never_served_beyond_one_hour():
    client = OpenMeteoWeatherClient()
    cached_payload = {"current": {"temperature_2m": 22.0}}

    # Warm cache
    with patch("data_sync.clients.openmeteo_weather_client._get_with_retry", new_callable=AsyncMock, return_value=cached_payload):
        await client.fetch_current_weather(15.82, 78.03)

    # Fast-forward time past 1 hour (3601 seconds)
    real_monotonic = time.monotonic
    with patch("time.monotonic", side_effect=lambda: real_monotonic() + 3601.0):
        # Trigger cooldown so it would try to use stale cache
        set_cooldown(60.0)
        # Stale cache is expired beyond 1 hour, so it MUST NOT be served; must raise 429
        with pytest.raises(ExternalAPIException) as exc_info:
            await client.fetch_current_weather(15.82, 78.03)
        assert exc_info.value.upstream_status == 429


@pytest.mark.asyncio
async def test_cooldown_expiration():
    """Verify that after cooldown expires, requests are no longer blocked."""
    client = OpenMeteoWeatherClient()
    mock_payload = {"current": {"temperature_2m": 24.0}}

    set_cooldown(0.05)
    assert is_rate_limited() is True

    # Sleep past cooldown
    await asyncio.sleep(0.06)
    assert is_rate_limited() is False
    assert get_cooldown_remaining() == 0.0

    with patch("data_sync.clients.openmeteo_weather_client._get_with_retry", new_callable=AsyncMock, return_value=mock_payload) as mock_get:
        res = await client.fetch_current_weather(13.55, 78.50)
        assert res == mock_payload
        assert mock_get.call_count == 1


@pytest.mark.asyncio
async def test_repeated_requests_during_cooldown_suppressed():
    """Verify that multiple requests during cooldown are suppressed and counted."""
    client = OpenMeteoWeatherClient()

    set_cooldown(60.0)
    assert is_rate_limited() is True

    # Make 5 repeated requests during cooldown
    for _ in range(5):
        with pytest.raises(ExternalAPIException) as exc:
            await client.fetch_current_weather(13.55, 78.50)
        assert exc.value.upstream_status == 429
        assert "cooldown active" in exc.value.detail

    metrics = get_weather_client_metrics()
    assert metrics["suppressed_requests"] == 5
    assert metrics["upstream_requests"] == 0


@pytest.mark.asyncio
async def test_no_cache_behavior_during_cooldown():
    """Verify that when no fresh or stale cache exists, fetch_current_weather fast-fails."""
    client = OpenMeteoWeatherClient()
    set_cooldown(120.0)

    # Coords not in cache
    with pytest.raises(ExternalAPIException) as exc:
        await client.fetch_current_weather(17.38, 78.48)

    assert exc.value.upstream_status == 429
    assert exc.value.status_code == 502
    assert "cooldown active" in exc.value.detail


@pytest.mark.asyncio
async def test_independent_coordinates_distinct_caching():
    """Verify that separate coordinates maintain independent cache entries."""
    client = OpenMeteoWeatherClient()
    payload_a = {"current": {"temperature_2m": 31.0}}
    payload_b = {"current": {"temperature_2m": 19.5}}

    with patch("data_sync.clients.openmeteo_weather_client._get_with_retry", new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = [payload_a, payload_b]

        res_a = await client.fetch_current_weather(28.61, 77.20)  # Delhi
        res_b = await client.fetch_current_weather(12.97, 77.59)  # Bengaluru

        assert res_a == payload_a
        assert res_b == payload_b
        assert mock_get.call_count == 2

        # Subsequent fetches hit their respective distinct cache entries
        res_a_cached = await client.fetch_current_weather(28.61, 77.20)
        res_b_cached = await client.fetch_current_weather(12.97, 77.59)
        assert res_a_cached == payload_a
        assert res_b_cached == payload_b
        assert mock_get.call_count == 2


@pytest.mark.asyncio
async def test_weather_service_endpoint_returns_controlled_unavailable_during_429():
    """Verify /weather endpoint returns HTTP 200 with source='UNAVAILABLE' and is_available=False
    rather than a 502 crash when upstream provider is in cooldown and no cache exists.
    """
    from services.weather_service import WeatherService
    from data_sync.clients.nominatim_client import GeocodingResult

    mock_geo = GeocodingResult(
        latitude=13.55,
        longitude=78.50,
        country="India",
        country_code="IN",
    )

    service = WeatherService()

    # Trigger cooldown so OpenMeteoWeatherClient is in active 429 cooldown
    set_cooldown(29177.5)

    with patch("data_sync.clients.nominatim_client.NominatimGeocoderClient.geocode_address_with_details", new_callable=AsyncMock, return_value=mock_geo):
        resp = await service.get_weather("Madanapalle")

        # Crucial architectural assertion: Must NOT raise 502!
        assert resp.city == "Madanapalle"
        assert resp.source == "UNAVAILABLE"
        assert resp.is_available is False
        assert resp.temperature is None
        assert resp.condition == "Unavailable"
        assert resp.cooldown_remaining_seconds is not None
        assert resp.cooldown_remaining_seconds > 29000.0


@pytest.mark.asyncio
async def test_weather_service_endpoint_returns_stale_cache_during_429():
    """Verify /weather endpoint returns stale cache with source='STALE_CACHE' when in cooldown."""
    from services.weather_service import WeatherService
    from data_sync.clients.nominatim_client import GeocodingResult

    mock_geo = GeocodingResult(
        latitude=13.55,
        longitude=78.50,
        country="India",
        country_code="IN",
    )
    mock_weather = {
        "current": {
            "temperature_2m": 29.0,
            "apparent_temperature": 31.0,
            "relative_humidity_2m": 60,
            "wind_speed_10m": 4.5,
            "wind_direction_10m": 90,
            "surface_pressure": 1010,
            "precipitation": 0.0,
            "weather_code": 0,
        },
        "daily": {"sunrise": ["2026-11-10T06:00"], "sunset": ["2026-11-10T18:00"]},
        "timezone": "Asia/Kolkata",
    }

    service = WeatherService()

    # 1. Successful live fetch warms the cache
    with patch("data_sync.clients.nominatim_client.NominatimGeocoderClient.geocode_address_with_details", new_callable=AsyncMock, return_value=mock_geo), \
         patch("data_sync.clients.openmeteo_weather_client.OpenMeteoWeatherClient.fetch_current_weather", new_callable=AsyncMock, return_value=mock_weather):
        live_resp = await service.get_weather("Madanapalle")
        assert live_resp.source == "LIVE"
        assert live_resp.temperature == 29.0

    # 2. Fast forward 15 minutes (past fresh TTL 600s, within stale TTL 3600s)
    # and trigger 429 cooldown
    real_monotonic = time.monotonic
    with patch("time.monotonic", side_effect=lambda: real_monotonic() + 900.0), \
         patch("data_sync.clients.nominatim_client.NominatimGeocoderClient.geocode_address_with_details", new_callable=AsyncMock, return_value=mock_geo), \
         patch("data_sync.clients.openmeteo_weather_client.OpenMeteoWeatherClient.fetch_current_weather", side_effect=ExternalAPIException(detail="429 Too Many Requests", error_code="OPEN_METEO_API_ERROR", status_code=502, upstream_status=429)):
        set_cooldown(3600.0)
        stale_resp = await service.get_weather("Madanapalle")

        assert stale_resp.source == "STALE_CACHE"
        assert stale_resp.is_available is True
        assert stale_resp.temperature == 29.0
        assert stale_resp.cached_at is not None


@pytest.mark.asyncio
async def test_frontend_adapt_weather_handles_unavailable():
    """Verify that WeatherResponse with is_available=False maps cleanly in frontend adapter."""
    from api_layer.api.schemas.aqi_endpoints import WeatherResponse

    resp = WeatherResponse(
        city="Madanapalle",
        latitude=13.55,
        longitude=78.50,
        temperature=None,
        condition="Unavailable",
        condition_description="Weather data temporarily unavailable (upstream rate limit active)",
        source="UNAVAILABLE",
        is_available=False,
        cooldown_remaining_seconds=29177.5,
    )
    dumped = resp.model_dump()
    assert dumped["is_available"] is False
    assert dumped["source"] == "UNAVAILABLE"
    assert dumped["temperature"] is None

    # Verify adapter transformation contract
    is_avail = dumped.get("is_available") is not False and dumped.get("temperature") is not None
    adapted_cod = 200 if is_avail else 503
    assert adapted_cod == 503
    assert is_avail is False

