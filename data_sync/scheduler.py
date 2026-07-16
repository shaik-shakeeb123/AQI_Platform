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

# Verify script is running inside a virtual environment (.venv)
if sys.prefix == sys.base_prefix:
    print(
        "CRITICAL ERROR: Ingestion scheduler must be run inside the virtual environment (.venv).\n"
        "Please execute using: .venv\\Scripts\\python.exe data_sync/scheduler.py",
        file=sys.stderr
    )
    sys.exit(1)

# Enable unbuffered / line-buffered output for real-time logging
try:
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)
except Exception:
    pass

configure_logging()
logger = get_logger("scheduler")

LOCK_FILE = "scheduler.lock"


async def run_ingestion_job() -> None:
    """Check lock file status, run incremental AQI ingestion, and release lock."""
    settings = get_settings()
    lock_threshold = settings.LOCK_FILE_AGE_THRESHOLD_SECS
    target_records = settings.SCHEDULED_TARGET_RECORDS
    batch_size = settings.SCHEDULED_BATCH_SIZE

    # 1. Lock File Check (Overlap Prevention & Crash Recovery)
    if os.path.exists(LOCK_FILE):
        try:
            mtime = os.path.getmtime(LOCK_FILE)
            age = time.time() - mtime
            if age > lock_threshold:
                logger.warning(
                    "Stale lock file found (age: %.1fs, threshold: %ds). "
                    "Recovering from previous crash by deleting stale lock and proceeding.",
                    age,
                    lock_threshold,
                )
                try:
                    os.remove(LOCK_FILE)
                except Exception as err:
                    logger.error("Failed to remove stale lock file: %s", str(err))
                    return
            else:
                logger.warning(
                    "Active lock file found (age: %.1fs, threshold: %ds). "
                    "Ingestion run is already in progress or overlapping. Skipping this run.",
                    age,
                    lock_threshold,
                )
                return
        except Exception as err:
            logger.error("Failed checking lock file: %s", str(err))
            return

    # 2. Lock Acquisition
    try:
        with open(LOCK_FILE, "w") as f:
            f.write(
                f"PID: {os.getpid()}\n"
                f"Started at: {datetime.now(timezone.utc).isoformat()}\n"
            )
        logger.info("Acquired lock file '%s' for current ingestion run.", LOCK_FILE)
    except Exception as err:
        logger.error("Failed to create lock file: %s. Skipping ingestion run.", str(err))
        return

    # 3. DB Session & Service Run
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
    except Exception as err:
        logger.exception("Error occurred during scheduled ingestion run: %s", str(err))
    finally:
        db.close()
        # 4. Lock Release
        try:
            if os.path.exists(LOCK_FILE):
                os.remove(LOCK_FILE)
                logger.info("Released lock file '%s'.", LOCK_FILE)
        except Exception as err:
            logger.error("Failed to remove lock file during cleanup: %s", str(err))


async def main() -> None:
    """Async main loop that sleeps for the configured interval between runs."""
    settings = get_settings()
    interval = settings.INGESTION_INTERVAL_SECONDS
    logger.info(
        "Starting Standalone Ingestion Scheduler. Interval: %d seconds. "
        "Target Locations: %d. Lock Threshold: %d seconds.",
        interval,
        settings.SCHEDULED_TARGET_RECORDS,
        settings.LOCK_FILE_AGE_THRESHOLD_SECS,
    )

    while True:
        try:
            start_time = time.time()
            await run_ingestion_job()

            # Dynamic sleep calculation to respect interval precisely
            elapsed = time.time() - start_time
            sleep_time = max(0.1, interval - elapsed)
            logger.info("Next ingestion run scheduled in %.1f seconds.", sleep_time)
            await asyncio.sleep(sleep_time)
        except asyncio.CancelledError:
            logger.info("Scheduler received cancellation signal. Exiting.")
            break
        except Exception as err:
            logger.exception("Unexpected error in scheduler loop: %s", str(err))
            # Prevent rapid failure spinning
            await asyncio.sleep(10)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Scheduler stopped by user request (KeyboardInterrupt).")
