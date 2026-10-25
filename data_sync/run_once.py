import os
import sys
import asyncio
import argparse
from typing import Optional, List

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


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    """Parse and validate command-line arguments for one-time ingestion."""
    parser = argparse.ArgumentParser(
        prog="run_once",
        description="Execute a one-time AQI ingestion run with optional dry-run and batch bounds.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Execute ingestion cycle without persisting durable database modifications.",
    )
    parser.add_argument(
        "--batch-size",
        "--limit",
        dest="limit",
        type=int,
        default=None,
        help="Explicit upper bound on number of locations to poll (positive integer).",
    )
    args = parser.parse_args(argv)
    if args.limit is not None and args.limit <= 0:
        parser.error(f"--batch-size/--limit must be a positive integer, got {args.limit}")
    return args


async def main(argv: Optional[List[str]] = None) -> int:
    """Run the ingestion job exactly once and exit."""
    # When argv is None, default to [] so programmatic callers in tests don't inherit pytest sys.argv
    cli_args = argv if argv is not None else []
    try:
        args = parse_args(cli_args)
    except SystemExit as se:
        return se.code if isinstance(se.code, int) else 2

    logger.info(
        "Starting one-time AQI ingestion job (dry_run=%s, limit=%s)...",
        args.dry_run, args.limit,
    )
    try:
        status = await run_ingestion_job(dry_run=args.dry_run, limit=args.limit)
        if status in ("SUCCESS", "DRY_RUN"):
            logger.info("One-time AQI ingestion job finished cleanly (status: %s).", status)
            return 0
        elif str(status).startswith("SKIPPED"):
            logger.info("One-time AQI ingestion job was skipped (status: %s).", status)
            return 0
        elif status == "PARTIAL":
            logger.warning("One-time AQI ingestion job completed with PARTIAL status (some stations had errors).")
            return 2
        else:
            logger.error("One-time AQI ingestion job failed (status: %s).", status)
            return 1
    except asyncio.CancelledError:
        logger.info("Ingestion job was cancelled.")
        return 1
    except Exception as err:
        logger.exception("Catastrophic error during one-time ingestion: %s", str(err))
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main(sys.argv[1:]))
    sys.exit(exit_code)
