# Manual Diagnostics for OpenAQ Integration

> [!CAUTION]
> **DO NOT RUN THESE SCRIPTS AGAINST A RESTRICTED OR PRODUCTION API KEY WITHOUT AUTHORIZATION.**
> These scripts make direct or live HTTP calls and are intended strictly for manual developer diagnostics in controlled environments.

## Safeguards
All scripts in this directory are protected by an environment variable guard.
They will exit immediately unless `ENABLE_MANUAL_OPERAQ_DIAGNOSTICS=true` is set.
None of these scripts start with `test_` to prevent accidental discovery by `pytest` or CI test runners.

## Available Scripts

1. `verify_auth.py` (formerly `test_auth.py`):
   Tests OpenAQ v3 authentication header formats (`X-API-Key`, `Authorization: Bearer`).
   **Warning:** Makes live HTTP requests to `api.openaq.org`.

2. `verify_key_format.py` (formerly `test_key.py`):
   Inspects the configured API key's length, prefix, and whitespace to check for formatting or copy-paste issues.

3. `inspect_headers.py` (formerly `test_provider_headers.py`):
   Sends a test request through `OpenAQAdapter` to a test reflection endpoint (`httpbin.org`) to inspect outgoing headers.

4. `dry_run_ingestion.py` (formerly `test_ingestion_dry_run.py`):
   Runs a dry run of the ingestion coordinator.
