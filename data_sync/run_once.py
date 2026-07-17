import os
import sys
import asyncio

# Add AQI_Backend root to system path to ensure reliable package imports
sys.path.append(os.path.abspath(os.path.dirname(__file__)))
ROOT_DIR = os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)
sys.path.insert(0, ROOT_DIR)

from data_sync.scheduler import run_ingestion_job
from api_layer.logging import configure_logging, get_logger

# Enable unbuffered / line-buffered output for real-time logging
try:
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)
except Exception:
    pass

configure_logging()
logger = get_logger("run_once")

async def main() -> int:
    """Run the ingestion job exactly once and exit."""
    logger.info("Starting one-time AQI ingestion job via GitHub Actions...")
    try:
        success = await run_ingestion_job()
        if success:
            logger.info("One-time AQI ingestion job completed successfully.")
            return 0
        else:
            logger.error("One-time AQI ingestion job encountered an error.")
            return 1
    except asyncio.CancelledError:
        logger.info("Ingestion job was cancelled.")
        return 1
    except Exception as err:
        logger.exception("Catastrophic error during one-time ingestion: %s", str(err))
        return 1

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
