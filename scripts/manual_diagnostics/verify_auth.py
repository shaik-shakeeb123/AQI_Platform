"""Manual diagnostic script to verify OpenAQ authentication header formats.

SAFEGUARD: Disabled by default. Set ENABLE_MANUAL_OPERAQ_DIAGNOSTICS=true to run.
"""
import os
import sys

if os.environ.get("ENABLE_MANUAL_OPERAQ_DIAGNOSTICS") != "true":
    sys.exit(
        "SAFEGUARD: Manual diagnostic script is disabled by default to prevent accidental "
        "live OpenAQ API calls. Set ENABLE_MANUAL_OPERAQ_DIAGNOSTICS=true in your environment to execute."
    )

import httpx
from api_layer.config import get_settings

settings = get_settings()
url = "https://api.openaq.org/v3/locations/431"
headers = {"X-API-Key": settings.OPENAQ_API_KEY}
r = httpx.get(url, headers=headers)
print("X-API-Key status:", r.status_code)
if r.status_code != 200:
    print("Trying Authorization: Bearer")
    r2 = httpx.get(url, headers={"Authorization": f"Bearer {settings.OPENAQ_API_KEY}"})
    print("Bearer status:", r2.status_code)
    if r2.status_code != 200:
        print("Trying X-API-KEY (uppercase)")
        r3 = httpx.get(url, headers={"X-API-KEY": settings.OPENAQ_API_KEY})
        print("Uppercase status:", r3.status_code)
