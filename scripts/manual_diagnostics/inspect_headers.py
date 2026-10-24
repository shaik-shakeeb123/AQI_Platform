"""Manual diagnostic script to inspect OpenAQAdapter outgoing headers using httpbin.

SAFEGUARD: Disabled by default. Set ENABLE_MANUAL_OPERAQ_DIAGNOSTICS=true to run.
"""
import os
import sys

if os.environ.get("ENABLE_MANUAL_OPERAQ_DIAGNOSTICS") != "true":
    sys.exit(
        "SAFEGUARD: Manual diagnostic script is disabled by default. "
        "Set ENABLE_MANUAL_OPERAQ_DIAGNOSTICS=true in your environment to execute."
    )

import asyncio
from data_sync.ingestion.provider import OpenAQAdapter
from api_layer.config import get_settings

async def inspect_provider_headers():
    settings = get_settings()
    adapter = OpenAQAdapter()
    
    # Hit httpbin to inspect serialized outgoing headers
    adapter.base_url = "https://httpbin.org"
    try:
        res = await adapter._make_governed_request("/get")
        print("Headers sent by adapter:")
        for k, v in res.get("headers", {}).items():
            if k.lower() == "x-api-key":
                print(f"{k}: {v[:4]}... (length: {len(v)})")
            elif k.lower() not in ["host", "user-agent", "accept", "accept-encoding"]:
                print(f"{k}: {v}")
    finally:
        await adapter.close()

if __name__ == "__main__":
    asyncio.run(inspect_provider_headers())
