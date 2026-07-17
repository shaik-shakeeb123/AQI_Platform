"""Standalone background scheduler for automated, incremental AQI ingestion.

Runs every 30 minutes (configurable via INGESTION_INTERVAL_SECONDS) in an independent
asyncio loop, fetching fresh AQI data, running duplicate checks, calculating CPCB AQI,
and storing records. Prevents overlapping runs using a lock-file strategy with automatic
stale lock recovery.
"""

import os
import sys
import time
import asyncio
import signal
from datetime import datetime, timezone

# Add AQI_Backend root to system path to ensure reliable package imports
sys.path.append(os.path.abspath(os.path.dirname(__file__)))
ROOT_DIR = os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)
sys.path.insert(0, ROOT_DIR)
from api_layer.config import get_settings
from database.connection import SessionLocal
from data_sync.sync_service import POCSyncService
from api_layer.logging import configure_logging, get_logger

# Enable unbuffered / line-buffered output for real-time logging
try:
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)
except Exception:
    pass

configure_logging()
logger = get_logger("scheduler")

async def run_ingestion_job() -> bool:
    """Run incremental AQI ingestion."""
    settings = get_settings()
    target_records = settings.SCHEDULED_TARGET_RECORDS
    batch_size = settings.SCHEDULED_BATCH_SIZE

    db = SessionLocal()
    try:
        logger.info(
            "Starting scheduled ingestion run (target_records=%d, batch_size=%d)...",
            target_records,
            batch_size,
        )
        service = POCSyncService(db)
        res = await service.sync_openaq_test(target_records=target_records, batch_size=batch_size)
        logger.info("Scheduled ingestion completed successfully. Summary: %s", res)
        return True
    except asyncio.CancelledError:
        logger.info("Ingestion run was cancelled.")
        raise
    except Exception as err:
        logger.exception("Error occurred during scheduled ingestion run: %s", str(err))
        return False
    finally:
        db.close()


async def main() -> None:
    """Async main loop that sleeps for the configured interval between runs."""
    loop = asyncio.get_running_loop()
    shutdown_event = asyncio.Event()
    
    def handle_sigterm():
        logger.info("Received SIGTERM from Render. Initiating cooperative shutdown...")
        shutdown_event.set()
            
    try:
        loop.add_signal_handler(signal.SIGTERM, handle_sigterm)
    except NotImplementedError:
        # add_signal_handler is not implemented on Windows natively
        pass

    settings = get_settings()
    interval = settings.INGESTION_INTERVAL_SECONDS
    logger.info(
        "Starting Standalone Ingestion Scheduler. Interval: %d seconds. "
        "Target Locations: %d.",
        interval,
        settings.SCHEDULED_TARGET_RECORDS,
    )

    while not shutdown_event.is_set():
        try:
            start_time = time.time()
            await run_ingestion_job()

            if shutdown_event.is_set():
                logger.info("Shutdown requested. Exiting scheduler loop cleanly.")
                break

            # Dynamic sleep calculation to respect interval precisely
            elapsed = time.time() - start_time
            sleep_time = max(0.1, interval - elapsed)
            logger.info("Next ingestion run scheduled in %.1f seconds.", sleep_time)
            
            # Cooperative sleep: wait_for will raise TimeoutError if the time expires without shutdown
            try:
                await asyncio.wait_for(shutdown_event.wait(), timeout=sleep_time)
                # If we get here without TimeoutError, shutdown_event was set during sleep
                logger.info("Shutdown requested during sleep. Exiting scheduler loop cleanly.")
                break
            except asyncio.TimeoutError:
                pass
                
        except asyncio.CancelledError:
            logger.info("Scheduler received cancellation signal. Exiting.")
            break
        except Exception as err:
            logger.exception("Unexpected error in scheduler loop: %s", str(err))
            if not shutdown_event.is_set():
                # Prevent rapid failure spinning but still wake on shutdown
                try:
                    await asyncio.wait_for(shutdown_event.wait(), timeout=10)
                    break
                except asyncio.TimeoutError:
                    pass


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Scheduler stopped by user request (KeyboardInterrupt).")
