"""Manual diagnostic script to inspect OpenAQ API key formatting.

SAFEGUARD: Disabled by default. Set ENABLE_MANUAL_OPERAQ_DIAGNOSTICS=true to run.
"""
import os
import sys

if os.environ.get("ENABLE_MANUAL_OPERAQ_DIAGNOSTICS") != "true":
    sys.exit(
        "SAFEGUARD: Manual diagnostic script is disabled by default. "
        "Set ENABLE_MANUAL_OPERAQ_DIAGNOSTICS=true in your environment to execute."
    )

sys.path.insert(0, os.path.abspath('.'))
from api_layer.config import get_settings

key = get_settings().OPENAQ_API_KEY
print(f'Len: {len(key)}, Start: {key[:4]}, HasSpace: {" " in key}, Quotes: {key.startswith(chr(34)) or key.startswith(chr(39))}')
