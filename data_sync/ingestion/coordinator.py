"""Main orchestrator for the ingestion pipeline."""

from __future__ import annotations

import asyncio
import time
import uuid
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional

from sqlalchemy.orm import Session
from sqlalchemy import select, func, text, desc
from sqlalchemy.exc import IntegrityError

from api_layer.logging import get_logger
from data_sync.ingestion.models import IngestionRun, IngestionLocation
from data_sync.ingestion.metrics import IngestionMetrics
from data_sync.ingestion.planner import IngestionPlanner
from data_sync.ingestion.provider import OpenAQAdapter
from data_sync.ingestion.processor import IngestionProcessor
from data_sync.clients.nominatim_client import NominatimGeocoderClient
from data_sync.clients.openmeteo_weather_client import OpenMeteoWeatherClient
from api_layer.config import get_settings

logger = get_logger(__name__)

# Advisory lock constant for AQI Ingestion
INGESTION_LOCK_ID = 8273645

class IngestionCoordinator:
    """Orchestrates metadata sync and measurement ingestion with safety bounds."""

    def __init__(self, db: Session, dry_run: bool = False) -> None:
        self.db = db
        self.dry_run = dry_run
        self.run_id = str(uuid.uuid4())
        self.provider = "OpenAQ"
        
        self.metrics = IngestionMetrics()
        self.provider_adapter = OpenAQAdapter(metrics=self.metrics)
        
        # Initialize processor clients
        self.geocoder = NominatimGeocoderClient()
        self.weather_client = OpenMeteoWeatherClient()
        self.processor = IngestionProcessor(
            db=self.db,
            metrics=self.metrics,
            geocoder=self.geocoder,
            weather_client=self.weather_client
        )
        self.planner = IngestionPlanner(self.db, self.provider)
        
        # Will be populated
        self.run_record: Optional[IngestionRun] = None
        self._lock_acquired: bool = False

    async def _acquire_lock(self) -> bool:
        """Acquire Postgres session-level advisory lock."""
        result = self.db.execute(
            text(f"SELECT pg_try_advisory_lock({INGESTION_LOCK_ID})")
        ).scalar()
        self.db.commit()
        self._lock_acquired = bool(result)
        return self._lock_acquired

    async def _release_lock(self) -> None:
        """Release Postgres session-level advisory lock."""
        if not self._lock_acquired:
            return
        try:
            self.db.execute(text(f"SELECT pg_advisory_unlock({INGESTION_LOCK_ID})"))
            self.db.commit()
        except Exception as e:
            logger.warning("Could not release advisory lock: %s", e)
        finally:
            self._lock_acquired = False

    async def _sync_metadata(self) -> None:
        """Fetch all India locations and update the location catalog."""
        logger.info("[%s] Starting Metadata Sync", self.run_id)
        page = 1
        limit = 100
        
        while True:
            res = await self.provider_adapter.get_locations(
                countries_id=9, limit=limit, page=page, order_by="id", sort_order="asc"
            )
            results = res.get("results", [])
            if not results:
                break
                
            loc_ids = [r.get("id") for r in results if r.get("id") is not None]
            existing_locs = self.db.scalars(
                select(IngestionLocation).where(
                    IngestionLocation.provider == self.provider,
                    IngestionLocation.provider_location_id.in_(loc_ids)
                )
            ).all()
            existing_map = {loc.provider_location_id: loc for loc in existing_locs}
                
            for raw_loc in results:
                loc_id = raw_loc.get("id")
                if loc_id is None:
                    continue
                name = raw_loc.get("name", "Unknown")
                lat = (raw_loc.get("coordinates") or {}).get("latitude")
                lon = (raw_loc.get("coordinates") or {}).get("longitude")
                
                # Extract datetimeLast if present
                datetime_last = None
                if raw_loc.get("datetimeLast") and raw_loc["datetimeLast"].get("utc"):
                    try:
                        datetime_last = datetime.fromisoformat(
                            raw_loc["datetimeLast"]["utc"].replace("Z", "+00:00")
                        ).replace(tzinfo=None)
                    except ValueError:
                        pass
                
                db_loc = existing_map.get(loc_id)
                
                if not db_loc:
                    db_loc = IngestionLocation(
                        provider=self.provider,
                        provider_location_id=loc_id,
                        location_name=name,
                        latitude=lat,
                        longitude=lon,
                        provider_datetime_last=datetime_last,
                        is_active=True
                    )
                    self.db.add(db_loc)
                else:
                    if datetime_last and (db_loc.provider_datetime_last is None or datetime_last > db_loc.provider_datetime_last):
                        db_loc.provider_datetime_last = datetime_last
                    # Revive location if it has new metadata
                    if datetime_last and datetime_last > datetime.now() - timedelta(days=7):
                        db_loc.is_active = True
                        
                        
            self.db.flush()
            
            # Check pagination
            meta = res.get("meta", {})
            found = meta.get("found", 0)
            if isinstance(found, str) and found.startswith(">"):
                found = int(found[1:]) + 1 # Force loop to continue if >
            if page * limit >= found and not (isinstance(meta.get("found"), str) and ">" in meta.get("found")):
                break
                
            page += 1
            
        if not self.dry_run:
            self.db.commit()
            
        logger.info("[%s] Completed Metadata Sync", self.run_id)

    async def _should_run_metadata_sync(self) -> bool:
        """Decide if a metadata sync is needed (e.g., every 6 hours or if empty catalog)."""
        count = self.db.scalar(select(func.count()).select_from(IngestionLocation))
        if count == 0:
            return True
            
        # Check time since last global metadata sync using the first active location's updated_at?
        # Actually a simpler heuristic: check if any station was added/updated in the last 6h
        # Wait, just checking if we haven't synced ANY location's metadata for 6h.
        last_sync = self.db.scalar(
            select(func.max(IngestionLocation.updated_at))
        )
        if last_sync and last_sync < datetime.now() - timedelta(hours=6):
            return True
            
        return False


    async def _check_db_backed_hourly_budget(self) -> bool:
        """Pre-flight check: query ingestion_runs for requests issued in the last 60 minutes.

        The in-process RequestGovernor tracks hourly usage in a deque that resets on
        process restart (e.g. every GitHub Actions invocation). This method provides a
        DB-backed, cross-process budget guard so two back-to-back GA runs cannot together
        exceed the OpenAQ hourly limit.

        Budget integrity invariants enforced:
        1. openaq_requests ALREADY includes retries (governor increments on every attempt).
           We query SUM(openaq_requests) without adding openaq_retries to prevent double counting.
        2. COALESCE(finished_at, started_at) >= NOW() - INTERVAL '1 hour' captures runs that
           started earlier but concluded within the trailing hour.
        3. status != 'DRY_RUN' includes completed, partial, failed, and crashed runs.
        4. The in-process governor's hourly_budget is set directly to the remaining headroom
           (budget - trailing_hour_requests), eliminating synthetic timestamp priming and roll-off skew.

        Returns:
            True  – budget has headroom; ingestion may proceed.
            False – budget is exhausted; this run must not issue any OpenAQ requests.
        """
        from sqlalchemy import text as _text
        settings = get_settings()
        budget = settings.OPENAQ_HOURLY_REQUEST_BUDGET

        try:
            result = self.db.execute(
                _text(
                    "SELECT COALESCE(SUM(openaq_requests), 0) "
                    "FROM ingestion_runs "
                    "WHERE provider = :provider "
                    "AND COALESCE(finished_at, started_at) >= NOW() - INTERVAL '1 hour' "
                    "AND status != 'DRY_RUN'"
                ),
                {"provider": self.provider},
            ).scalar()
            trailing_hour_requests = int(result or 0)
        except Exception as exc:
            # DB unavailable → fail closed: do not proceed with ingestion.
            logger.error(
                "[%s] DB-backed hourly budget check failed (%s). Aborting run to prevent "
                "over-quota OpenAQ requests.",
                self.run_id, exc,
            )
            return False

        if trailing_hour_requests >= budget:
            logger.warning(
                "[%s] DB-backed hourly budget exhausted: %d requests in trailing 60 "
                "minutes (budget=%d). Skipping this run.",
                self.run_id, trailing_hour_requests, budget,
            )
            return False

        remaining = budget - trailing_hour_requests
        logger.info(
            "[%s] DB-backed hourly budget OK: %d requests in trailing hour, %d remaining "
            "(budget=%d).",
            self.run_id, trailing_hour_requests, remaining, budget,
        )
        # Set the governor's hourly budget cap directly to the remaining headroom for this run.
        # This guarantees this process cannot exceed `remaining` requests.
        # Eliminates synthetic timestamp priming and rolling window edge-case bugs.
        gov = self.provider_adapter.governor
        gov.hourly_budget = remaining
        gov._request_timestamps.clear()

        return True

    async def _ingest_measurements(self) -> Optional[str]:
        """Plan and execute incremental measurement ingestion."""
        # 1. Read watermark
        watermark_before = self.planner.get_watermark(resource="measurements")
        self.run_record.watermark_before = watermark_before
        
        # 2. Get planned locations
        locations = self.planner.plan_measurement_ingestion()
        self.metrics.locations_examined = len(locations)
        
        if not locations:
            logger.info("[%s] No active locations need polling.", self.run_id)
            return
            
        logger.info("[%s] Planned polling for %d active locations.", self.run_id, len(locations))
        
        now = datetime.now()
        has_failures = False
        queue = asyncio.Queue()
        db_queue = asyncio.Queue()
        for loc in locations:
            queue.put_nowait(loc)

        def _sync_commit_batch(batch):
            for loc, records, new_time in batch:
                if not records:
                    continue
                for r in records:
                    try:
                        with self.db.begin_nested():
                            self.db.add(r)
                            self.db.flush()
                        self.metrics.records_stored += 1
                        if new_time and (loc.last_successful_ingestion_at is None or new_time > loc.last_successful_ingestion_at):
                            loc.last_successful_ingestion_at = new_time
                    except IntegrityError:
                        self.metrics.duplicates_skipped += 1
            
            if not self.dry_run:
                if self.run_record:
                    self.run_record.openaq_requests = self.metrics.openaq_requests
                    self.run_record.openaq_retries = self.metrics.openaq_retries
                    self.run_record.openaq_errors = self.metrics.openaq_errors
                    self.run_record.records_stored = self.metrics.records_stored
                self.db.commit()

        async def _db_writer():
            batch = []
            while True:
                item = await db_queue.get()
                if item is None:
                    if batch:
                        _sync_commit_batch(batch)
                    break
                
                batch.append(item)
                if len(batch) >= 25:
                    _sync_commit_batch(batch)
                    batch = []
                db_queue.task_done()

        # Start the DB writer task
        writer_task = asyncio.create_task(_db_writer())

        # 3. Process locations (Concurrently, bounded by workers)
        async def _worker():
            nonlocal has_failures
            while not queue.empty():
                try:
                    loc = queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                    
                try:
                    res = await self.provider_adapter.get_latest_measurements(loc.provider_location_id)
                    
                    # If we reached here, the HTTP request succeeded (or returned expected empty data)
                    loc.last_synced_at = now
                    
                    results = res.get("results", [])
                    self.metrics.records_fetched += len(results)
                    
                    records_to_insert, new_time = await self.processor.process_and_store(loc, results)
                    if not records_to_insert and not new_time and results:
                         has_failures = True
                    else:
                         await db_queue.put((loc, records_to_insert, new_time))
                            
                except Exception as e:
                    has_failures = True
                    logger.error("[%s] Error processing location %d: %s", self.run_id, loc.provider_location_id, e)
                    from api_layer.exceptions import ExternalAPIException
                    if isinstance(e, ExternalAPIException) and e.status_code in (401, 403, 502):
                        if "authentication" in str(e.detail).lower() or "authorization" in str(e.detail).lower() or "401" in str(e.detail) or "403" in str(e.detail):
                            raise e
                finally:
                    self.metrics.locations_attempted += 1
                    queue.task_done()

        from api_layer.config import get_settings
        num_workers = min(get_settings().MAX_PROVIDER_CONCURRENCY, len(locations))
        workers = [asyncio.create_task(_worker()) for _ in range(num_workers)]
        
        try:
            await asyncio.gather(*workers)
        except Exception as e:
            for w in workers:
                if not w.done():
                    w.cancel()
            logger.error("[%s] Measurement ingestion aborted: %s", self.run_id, e)
            raise e
        finally:
            # Drain queue and cleanly stop writer, even on cancellation
            await db_queue.put(None)
            try:
                await writer_task
            except asyncio.CancelledError:
                pass
        
        # 4. Save new watermark (Just for observability, we track the max across active stations)
        latest_success = self.db.scalar(
            select(func.max(IngestionLocation.last_successful_ingestion_at))
            .where(IngestionLocation.provider == self.provider)
        )
        if latest_success and (not watermark_before or latest_success > watermark_before):
            self.planner.advance_watermark(resource="measurements", scope="all", new_watermark=latest_success)
            self.run_record.watermark_after = latest_success
        else:
            self.run_record.watermark_after = watermark_before
            
        return "PARTIAL" if has_failures else "SUCCESS"

    async def execute(self) -> str:
        """Run the end-to-end ingestion cycle."""
        start_time = time.time()
        logger.info("[%s] Starting Ingestion Coordinator", self.run_id)

        # Open transaction
        try:
            # 1. Acquire Lock (session-scoped exclusive advisory lock)
            if not await self._acquire_lock():
                logger.warning("Another ingestion process is currently holding the advisory lock. Aborting.")
                return "SKIPPED_LOCKED"

            # 2. Clean up orphaned RUNNING runs from previous crashed processes
            try:
                self.db.execute(
                    text(
                        "UPDATE ingestion_runs "
                        "SET status = 'CRASHED', finished_at = CURRENT_TIMESTAMP, "
                        "error_message = 'Process terminated unexpectedly (orphaned RUNNING status)' "
                        "WHERE provider = :provider AND status = 'RUNNING' AND run_id != :current_run_id"
                    ),
                    {"provider": self.provider, "current_run_id": self.run_id}
                )
                self.db.commit()
            except Exception as e:
                logger.warning("[%s] Failed to clean up orphaned runs: %s", self.run_id, e)
                
            # 3. Setup Run Record
            self.run_record = IngestionRun(
                run_id=self.run_id,
                provider=self.provider,
                mode="SCHEDULED",
                dry_run=self.dry_run,
                status="RUNNING"
            )
            self.db.add(self.run_record)
            if not self.dry_run:
                self.db.commit()
            else:
                self.db.flush()

            # 5. DB-backed cross-process hourly budget pre-flight check
            # MUST execute BEFORE metadata sync to prevent metadata requests when budget is exhausted!
            if not await self._check_db_backed_hourly_budget():
                logger.warning(
                    "[%s] Hourly OpenAQ request budget exhausted in DB. "
                    "This run will be recorded as SKIPPED.",
                    self.run_id,
                )
                if self.run_record:
                    self.run_record.status = "SKIPPED"
                return "SKIPPED_BUDGET"

            # 6. Metadata Sync (now guarded by budget check)
            if await self._should_run_metadata_sync():
                await self._sync_metadata()

            # 7. Measurement Ingestion
            ingest_status = await self._ingest_measurements()
            if ingest_status is None:
                ingest_status = "SUCCESS"  # e.g., if no locations planned
            
            # Finalize Status
            self.run_record.status = ingest_status
            
        except asyncio.CancelledError:
            logger.info("[%s] Ingestion was cancelled.", self.run_id)
            if self.run_record:
                self.run_record.status = "CANCELLED"
            raise
        except Exception as e:
            logger.exception("[%s] Ingestion failed: %s", self.run_id, e)
            try:
                self.db.rollback()
            except Exception:
                pass
            if self.run_record:
                self.run_record.status = "FAILED"
                self.run_record.error_message = str(e)
            return "FAILED"
            
        finally:
            if self.run_record:
                self.metrics.locations_skipped = max(0, self.metrics.locations_examined - self.metrics.locations_attempted)
                self.run_record.finished_at = datetime.now(timezone.utc).replace(tzinfo=None)
                self.run_record.execution_seconds = time.time() - start_time
                
                # Copy metrics to record
                metrics_dict = self.metrics.to_dict()
                for k, v in metrics_dict.items():
                    setattr(self.run_record, k, v)
                    
                logger.info("[%s] Completed. %s", self.run_id, self.metrics.summarize())
                
            await self.provider_adapter.close()
            
            # Since we used nested scopes/flushes and a single session, we commit everything.
            if not self.dry_run:
                if self.run_record:
                    self.run_record.openaq_requests = self.metrics.openaq_requests
                    self.run_record.openaq_retries = self.metrics.openaq_retries
                    self.run_record.openaq_errors = self.metrics.openaq_errors
                    self.run_record.records_stored = self.metrics.records_stored
                self.db.commit()
            else:
                self.db.rollback()
                logger.info("[%s] Dry run finished. Rolled back.", self.run_id)
                
            await self._release_lock()
                
        return self.run_record.status
