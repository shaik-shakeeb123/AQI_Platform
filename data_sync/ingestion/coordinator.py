"""Main orchestrator for the ingestion pipeline."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional

from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy import select, func, text, desc, or_
from sqlalchemy.exc import IntegrityError

from api_layer.logging import get_logger
from data_sync.ingestion.models import IngestionRun, IngestionLocation
from data_sync.ingestion.metrics import IngestionMetrics
from data_sync.ingestion.planner import IngestionPlanner
from data_sync.ingestion.provider import OpenAQAdapter
from data_sync.ingestion.processor import IngestionProcessor
from data_sync.data_processor import parse_and_validate_sensors_json, merge_sensor_maps
from data_sync.clients.nominatim_client import NominatimGeocoderClient
from data_sync.clients.openmeteo_weather_client import OpenMeteoWeatherClient
from api_layer.config import get_settings

logger = get_logger(__name__)

# Advisory lock constant for AQI Ingestion
INGESTION_LOCK_ID = 8273645

class IngestionCoordinator:
    """Orchestrates metadata sync and measurement ingestion with safety bounds."""

    def __init__(self, db: Session, dry_run: bool = False, batch_limit: Optional[int] = None) -> None:
        if batch_limit is not None:
            if not isinstance(batch_limit, int) or isinstance(batch_limit, bool) or batch_limit <= 0:
                raise ValueError(
                    f"Invalid batch_limit: {batch_limit!r}. Limit must be a positive non-zero integer."
                )
        self.db = db
        self.dry_run = dry_run
        self.batch_limit = batch_limit
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
        if hasattr(self.db, "expire_on_commit"):
            self.db.expire_on_commit = False
        
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

                # Extract and serialize sensors if present
                sensors = raw_loc.get("sensors")
                new_s_map = {}
                if sensors and isinstance(sensors, list):
                    for s in sensors:
                        if not isinstance(s, dict):
                            continue
                        s_id = s.get("id")
                        param = s.get("parameter") or {}
                        p_name = param.get("name") if isinstance(param, dict) else str(param) if param else ""
                        p_unit = param.get("units", "") if isinstance(param, dict) else ""
                        if s_id is not None and p_name:
                            new_s_map[str(s_id).strip()] = (p_name.strip().lower(), str(p_unit).strip())
                
                db_loc = existing_map.get(loc_id)
                
                if not db_loc:
                    sensors_json_val = json.dumps({k: list(v) for k, v in new_s_map.items()}) if new_s_map else "{}"
                    db_loc = IngestionLocation(
                        provider=self.provider,
                        provider_location_id=loc_id,
                        location_name=name,
                        latitude=lat,
                        longitude=lon,
                        provider_datetime_last=datetime_last,
                        is_active=True,
                        last_synced_at=datetime(2000, 1, 1),
                        sensors_json=sensors_json_val,
                    )
                    self.db.add(db_loc)
                else:
                    if datetime_last and (db_loc.provider_datetime_last is None or datetime_last > db_loc.provider_datetime_last):
                        db_loc.provider_datetime_last = datetime_last
                    # Revive location if it has new metadata
                    if datetime_last and datetime_last > datetime.now() - timedelta(days=7):
                        db_loc.is_active = True
                    # Safely merge sensor definitions without overwriting existing valid metadata
                    if new_s_map:
                        existing_sensors = parse_and_validate_sensors_json(db_loc.sensors_json)
                        merged = merge_sensor_maps(existing_sensors, new_s_map)
                        if merged:
                            db_loc.sensors_json = json.dumps({k: list(v) for k, v in merged.items()})
                    elif db_loc.sensors_json is None or db_loc.sensors_json == "":
                        # Upstream confirmed to have no sensors for this station
                        db_loc.sensors_json = "{}"
                        
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
        """Decide if a metadata sync is needed (empty catalog, stale metadata, or missing sensor mappings)."""
        count = self.db.scalar(select(func.count()).select_from(IngestionLocation))
        if count == 0:
            return True

        # Check if active stations lack sensor metadata (uninitialized None or empty string)
        # Note: Confirmed empty stations have sensors_json == "{}" and do not trigger full catalog sync.
        missing_count = self.db.scalar(
            select(func.count()).select_from(IngestionLocation).where(
                IngestionLocation.provider == self.provider,
                IngestionLocation.is_active == True,
                or_(
                    IngestionLocation.sensors_json == None,
                    IngestionLocation.sensors_json == "",
                )
            )
        )
        if missing_count and missing_count > 0:
            logger.info(
                "[%s] Metadata sync required: %d active stations lack sensor mappings.",
                self.run_id, missing_count
            )
            return True

        # Check time since last global metadata sync
        last_sync = self.db.scalar(
            select(func.max(IngestionLocation.updated_at))
        )
        if last_sync and last_sync < datetime.now() - timedelta(hours=6):
            return True

        return False

    async def repair_location_sensor_metadata(self, loc: IngestionLocation) -> bool:
        """Fetch targeted location metadata for a specific station missing sensor mappings."""
        try:
            res = await self.provider_adapter.get_location(loc.provider_location_id)
            results = res.get("results", [])
            raw_loc = results[0] if isinstance(results, list) and results else results if isinstance(results, dict) else {}
            sensors = raw_loc.get("sensors") if isinstance(raw_loc, dict) else None
            if sensors and isinstance(sensors, list):
                s_map = {}
                for s in sensors:
                    if not isinstance(s, dict):
                        continue
                    s_id = s.get("id")
                    param = s.get("parameter") or {}
                    p_name = param.get("name") if isinstance(param, dict) else str(param) if param else ""
                    p_unit = param.get("units", "") if isinstance(param, dict) else ""
                    if s_id is not None and p_name:
                        s_map[str(s_id).strip()] = (p_name.strip().lower(), str(p_unit).strip())
                if s_map:
                    existing = parse_and_validate_sensors_json(loc.sensors_json)
                    merged = merge_sensor_maps(existing, s_map)
                    loc.sensors_json = json.dumps({k: list(v) for k, v in merged.items()})
                    logger.info(
                        "[%s] Repaired sensor metadata for station %d (%d sensors mapped).",
                        self.run_id, loc.provider_location_id, len(merged)
                    )
                    return True
                else:
                    # Station returned empty sensor list upstream; mark as confirmed empty catalog
                    loc.sensors_json = "{}"
                    return False
            else:
                # No sensors array in response; mark as confirmed empty catalog
                loc.sensors_json = "{}"
                return False
        except Exception as e:
            logger.warning(
                "[%s] Targeted metadata repair failed for location %d: %s",
                self.run_id, loc.provider_location_id, e
            )
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
        locations = self.planner.plan_measurement_ingestion(limit=self.batch_limit)
        self.metrics.locations_examined = len(locations)
        
        if not locations:
            logger.info("[%s] No active locations need polling.", self.run_id)
            return "SUCCESS"
            
        logger.info("[%s] Planned polling for %d active locations.", self.run_id, len(locations))
        
        # Release the planning read transaction so self.db is NOT held open during async network polling
        if not self.dry_run:
            self.db.commit()

        now = datetime.now()
        has_failures = False
        queue = asyncio.Queue()
        db_queue = asyncio.Queue()
        for loc in locations:
            queue.put_nowait(loc)

        def _sync_commit_batch(batch):
            committed_records = 0
            for loc, status, records, new_time in batch:
                if status == "SUCCESS" and records:
                    for r in records:
                        try:
                            with self.db.begin_nested():
                                self.db.add(r)
                                self.db.flush()
                            committed_records += 1
                        except IntegrityError:
                            self.metrics.duplicates_skipped += 1
                    
                    if new_time and (loc.last_successful_ingestion_at is None or new_time > loc.last_successful_ingestion_at):
                        loc.last_successful_ingestion_at = new_time
                    loc.last_synced_at = now
                    self.metrics.locations_successful += 1

                elif status in ("EMPTY", "PROCESSING_ERROR"):
                    # HTTP request succeeded (either empty data or processing/validation failure).
                    # Advance last_synced_at to prevent immediate tight-loop hammering,
                    # but DO NOT advance last_successful_ingestion_at.
                    loc.last_synced_at = now

                elif status == "HTTP_ERROR":
                    # HTTP request failed (network timeout, 5xx, etc.).
                    # DO NOT advance last_synced_at or last_successful_ingestion_at!
                    # Station remains eligible for retry in the next run.
                    pass
            
            if not self.dry_run:
                try:
                    self.db.commit()
                    # Authoritative counter: increment ONLY after durable database commit
                    self.metrics.records_stored += committed_records
                    if self.run_record:
                        self.run_record.records_stored = self.metrics.records_stored
                        self.run_record.openaq_requests = self.metrics.openaq_requests
                        self.run_record.openaq_retries = self.metrics.openaq_retries
                        self.run_record.openaq_errors = self.metrics.openaq_errors
                except Exception as commit_err:
                    logger.error("[%s] Database commit failed in batch writer: %s", self.run_id, commit_err)
                    self.db.rollback()
                    raise commit_err
            else:
                # Dry run: records were not durably stored; records_stored remains 0
                pass

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
                except Exception as http_err:
                    has_failures = True
                    self.metrics.locations_http_errors += 1
                    logger.error("[%s] HTTP error fetching location %d: %s", self.run_id, loc.provider_location_id, http_err)
                    from api_layer.exceptions import ExternalAPIException
                    if isinstance(http_err, ExternalAPIException) and http_err.status_code in (401, 403, 502):
                        if "authentication" in str(http_err.detail).lower() or "authorization" in str(http_err.detail).lower() or "401" in str(http_err.detail) or "403" in str(http_err.detail):
                            raise http_err
                    # Network timeout / HTTP error: DO NOT advance last_synced_at.
                    await db_queue.put((loc, "HTTP_ERROR", [], None))
                    self.metrics.locations_attempted += 1
                    queue.task_done()
                    continue

                # HTTP call succeeded:
                results = res.get("results", [])
                self.metrics.records_fetched += len(results)

                if not results:
                    # Successful empty response: advance last_synced_at to prevent immediate hammering
                    self.metrics.locations_empty += 1
                    await db_queue.put((loc, "EMPTY", [], None))
                else:
                    try:
                        records_to_insert, new_time = await self.processor.process_and_store(loc, results)
                        if not records_to_insert and not new_time:
                            # Results existed but produced no valid records (malformed/invalid data)
                            has_failures = True
                            self.metrics.locations_processing_errors += 1
                            await db_queue.put((loc, "PROCESSING_ERROR", [], None))
                        else:
                            await db_queue.put((loc, "SUCCESS", records_to_insert, new_time))
                    except Exception as proc_err:
                        has_failures = True
                        self.metrics.locations_processing_errors += 1
                        logger.error("[%s] Error processing location %d: %s", self.run_id, loc.provider_location_id, proc_err)
                        await db_queue.put((loc, "PROCESSING_ERROR", [], None))

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
            if not self.dry_run:
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
            else:
                logger.info("[%s] Dry run: skipping orphaned runs cleanup.", self.run_id)

            # 3. Setup Run Record
            self.run_record = IngestionRun(
                run_id=self.run_id,
                provider=self.provider,
                mode="SCHEDULED",
                dry_run=self.dry_run,
                status="RUNNING",
                started_at=datetime.now(timezone.utc).replace(tzinfo=None),
            )
            if not self.dry_run:
                self.db.add(self.run_record)
                self.db.commit()

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
                    if hasattr(self.run_record, k):
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
                try:
                    self.db.commit()
                except Exception as commit_err:
                    logger.warning("[%s] Final commit encountered error: %s", self.run_id, commit_err)
            else:
                # 1. Roll back the main ingestion session FIRST.
                # Guarantees that any staged aqi_data inserts, ingestion_locations
                # updates, and ingestion_state watermark updates are permanently aborted.
                rollback_succeeded = False
                try:
                    self.db.rollback()
                    rollback_succeeded = True
                    logger.info("[%s] Dry run finished. Staged measurements and locations rolled back.", self.run_id)
                except Exception as rb_err:
                    logger.error("[%s] Error during dry run rollback: %s", self.run_id, rb_err)
                    if self.run_record:
                        self.run_record.status = "FAILED"
                        self.run_record.error_message = f"Dry-run rollback failed: {rb_err}"

                # 2. Persist the dry-run audit summary via an independent, short-lived session.
                # The audit transaction is strictly isolated from the rolled-back session:
                # it connects on its own transaction, adds ONLY the IngestionRun summary, and commits.
                # If audit persistence fails, staged measurements are already rolled back and cannot be committed.
                if rollback_succeeded and self.run_record:
                    try:
                        from sqlalchemy.engine import Engine, Connection
                        bind = self.db.get_bind() if hasattr(self.db, "get_bind") else None
                        if isinstance(bind, (Engine, Connection)):
                            AuditSession = sessionmaker(bind=bind, expire_on_commit=False)
                            with AuditSession() as audit_db:
                                audit_run = IngestionRun(
                                    run_id=self.run_id,
                                    provider=self.provider,
                                    mode=getattr(self.run_record, "mode", "SCHEDULED"),
                                    dry_run=True,
                                    status="DRY_RUN" if getattr(self.run_record, "status", None) == "SUCCESS" else getattr(self.run_record, "status", "DRY_RUN"),
                                    started_at=getattr(self.run_record, "started_at", None),
                                    finished_at=getattr(self.run_record, "finished_at", None),
                                    watermark_before=getattr(self.run_record, "watermark_before", None),
                                    watermark_after=getattr(self.run_record, "watermark_after", None),
                                    locations_examined=self.metrics.locations_examined,
                                    locations_attempted=self.metrics.locations_attempted,
                                    locations_skipped=self.metrics.locations_skipped,
                                    records_fetched=self.metrics.records_fetched,
                                    records_validated=self.metrics.records_validated,
                                    records_rejected=self.metrics.records_rejected,
                                    records_stored=0,  # Invariant: records_stored must remain zero in dry-run
                                    duplicates_skipped=self.metrics.duplicates_skipped,
                                    openaq_requests=self.metrics.openaq_requests,
                                    openaq_retries=self.metrics.openaq_retries,
                                    openaq_rate_limits=self.metrics.openaq_rate_limits,
                                    openaq_errors=self.metrics.openaq_errors,
                                    nominatim_requests=self.metrics.nominatim_requests,
                                    openmeteo_requests=self.metrics.openmeteo_requests,
                                    execution_seconds=getattr(self.run_record, "execution_seconds", None),
                                    error_message=getattr(self.run_record, "error_message", None),
                                )
                                audit_db.add(audit_run)
                                audit_db.commit()
                                logger.info(
                                    "[%s] Dry-run audit summary persisted to ingestion_runs (status: %s).",
                                    self.run_id, audit_run.status
                                )
                        else:
                            logger.info(
                                "[%s] Non-engine DB bind detected (test mock); skipping audit persistence.",
                                self.run_id
                            )
                    except Exception as audit_err:
                        logger.error("[%s] Failed to persist dry-run audit summary: %s", self.run_id, audit_err)
                        self.run_record.status = "FAILED"
                        self.run_record.error_message = f"Dry-run audit persistence failed: {audit_err}"
                
            await self._release_lock()
                
        return self.run_record.status
