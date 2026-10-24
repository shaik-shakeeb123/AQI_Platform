"""Manual diagnostic script to run a local dry run of the IngestionCoordinator.

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
sys.path.append(os.path.abspath(os.path.dirname(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.connection import SessionLocal
from data_sync.ingestion.coordinator import IngestionCoordinator
from api_layer.logging import configure_logging

configure_logging()

async def main():
    db = SessionLocal()
    try:
        coord = IngestionCoordinator(db=db, dry_run=True)
        # Force metadata sync manually once to test it
        await coord._sync_metadata()
        
        # Test measurements
        await coord._ingest_measurements()
        print("Dry run summary:", coord.metrics.summarize())
    finally:
        db.close()

if __name__ == "__main__":
    asyncio.run(main())
