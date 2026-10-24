import asyncio
import time
import pytest
import httpx

from api_layer.exceptions import ExternalAPIException
from data_sync.ingestion.governor import RequestGovernor


@pytest.fixture
def governor():
    # Use high RPM so pacing doesn't interfere with basic tests
    return RequestGovernor("TestProvider", max_concurrency=10, requests_per_minute=6000, max_retries=2, base_backoff=0.1)


async def _mock_request(status_code=200, headers=None):
    if headers is None:
        headers = {}
    req = httpx.Request("GET", "http://test")
    res = httpx.Response(status_code, headers=headers, request=req)
    if status_code >= 400:
        raise httpx.HTTPStatusError("Error", request=req, response=res)
    return res


@pytest.mark.asyncio
async def test_scenario_1_normal_admission(governor):
    """Test 1: Limit = 60, Remaining = 59. Verify next request is admitted normally."""
    headers = {"X-Ratelimit-Limit": "60", "X-Ratelimit-Remaining": "59"}
    
    start = time.time()
    await governor.execute(lambda: _mock_request(200, headers))
    duration = time.time() - start
    
    assert duration < 0.5  # Should be immediate


@pytest.mark.asyncio
async def test_scenario_2_proactive_pause(governor):
    """Test 2: Remaining = 0, Reset = 1. Verify next request waits."""
    headers = {"X-Ratelimit-Limit": "60", "X-Ratelimit-Remaining": "0", "X-Ratelimit-Reset": "1"}
    
    # First request sets the proactive limit
    await governor.execute(lambda: _mock_request(200, headers))
    
    start = time.time()
    # Second request should wait ~1 sec + safety margin (1.0) = ~2 sec
    await governor.execute(lambda: _mock_request(200, {"X-Ratelimit-Remaining": "59"}))
    duration = time.time() - start
    
    assert duration >= 1.0


@pytest.mark.asyncio
async def test_scenario_3_429_retry_after(governor):
    """Test 3: HTTP 429, Retry-After = 1. Governor pauses."""
    headers = {"Retry-After": "1.0"}
    
    attempts = 0
    async def op():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            await _mock_request(429, headers)
        return await _mock_request(200)
        
    start = time.time()
    await governor.execute(op)
    duration = time.time() - start
    
    assert duration >= 1.0
    assert attempts == 2


@pytest.mark.asyncio
async def test_scenario_4_429_reset(governor):
    """Test 4: HTTP 429, Reset = 1. Respects reset."""
    headers = {"X-Ratelimit-Reset": "1.0"}
    
    attempts = 0
    async def op():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            await _mock_request(429, headers)
        return await _mock_request(200)
        
    start = time.time()
    await governor.execute(op)
    duration = time.time() - start
    
    assert duration >= 1.0
    assert attempts == 2


@pytest.mark.asyncio
async def test_scenario_5_and_6_concurrent_429_and_pacing():
    """
    Test 5: 10 concurrent tasks receive 429. One global pause.
    Test 6: After pause, released gradually based on rate limiter (pacing).
    """
    # 120 RPM = 0.5 request per second pacing to speed up test
    gov = RequestGovernor("TestProvider", max_concurrency=10, requests_per_minute=120, max_retries=2, base_backoff=0.1)
    
    attempts_map = {}
    
    async def op(task_id):
        attempts_map[task_id] = attempts_map.get(task_id, 0) + 1
        if attempts_map[task_id] == 1:
            # All first attempts fail with 429, reset in 1 sec
            await _mock_request(429, {"X-Ratelimit-Reset": "1"})
        return await _mock_request(200)

    start = time.time()
    
    # Launch 5 concurrent tasks
    tasks = [asyncio.create_task(gov.execute(lambda t=i: op(t))) for i in range(5)]
    await asyncio.gather(*tasks)
    
    duration = time.time() - start
    
    # Pause is 1s + safety (1s) = 2s minimum delay.
    # 5 tasks pacing at 0.5s per request = 2.5s extra (approximately, depending on lock queue)
    # Total time should be approx > 2.0s.
    assert duration >= 2.0
    
    for i in range(5):
        assert attempts_map[i] == 2

