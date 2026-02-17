"""Abstract base scraper — every site-specific scraper inherits from this."""
from __future__ import annotations

import abc
import asyncio
import gc
import hashlib
import json
import random
import time
from pathlib import Path
from typing import Any, Optional

import structlog

from backend.config import COOKIE_TTL, RATE_LIMITS
from backend.database.crud import (
    finish_scraper_run,
    get_latest_scraper_run,
    start_scraper_run,
    upsert_job,
)
from backend.database.models import Job, JobStatus, ScraperRun, ScraperRunStatus
from backend.scrapers.visa_filter import is_eligible

log = structlog.get_logger(__name__)


class BaseScraper(abc.ABC):
    """Abstract base class for all JobBot scrapers.

    Subclasses must implement :meth:`scrape` and define a ``SITE`` class attribute.
    """

    SITE: str = ""

    def __init__(self, site: str, db_session_factory: Any) -> None:
        self.site = site
        self.db_session_factory = db_session_factory
        self._log = log.bind(site=self.site)

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def run(self) -> dict[str, Any]:
        """Main entry point called by the scheduler.

        Returns a stats dict with keys: site, jobs_found, jobs_new, status.
        """
        self._log.info("scraper.starting")
        stats: dict[str, Any] = {
            "site": self.site,
            "jobs_found": 0,
            "jobs_new": 0,
            "status": ScraperRunStatus.completed.value,
        }

        async with self.db_session_factory() as db:
            # Check if this site is effectively disabled (too many consecutive zeros)
            latest_run = await get_latest_scraper_run(db, self.site)
            if latest_run and latest_run.consecutive_zero_runs >= 5:
                self._log.warning(
                    "scraper.disabled",
                    reason="too many consecutive zero runs",
                    consecutive=latest_run.consecutive_zero_runs,
                )
                stats["status"] = ScraperRunStatus.disabled.value
                return stats

            run = await start_scraper_run(db, self.site)
            await db.commit()

        try:
            self._log.info("scraper.scraping")
            jobs: list[dict] = await self.scrape()
            gc.collect()

            jobs_new = 0
            async with self.db_session_factory() as db:
                for job_data in jobs:
                    try:
                        eligible, reason = is_eligible(job_data)
                        if not eligible:
                            self._log.info(
                                "scraper.job_skipped_visa_filter",
                                title=job_data.get("title", ""),
                                company=job_data.get("company", ""),
                                reason=reason,
                            )
                            job_data["status"] = JobStatus.skipped.value
                            job_data.setdefault("raw_data", {})
                            if isinstance(job_data.get("raw_data"), dict):
                                job_data["raw_data"]["_skip_reason"] = reason
                        _job, is_new = await self._dedup_job(db, job_data)
                        if is_new and eligible:
                            jobs_new += 1
                    except Exception as exc:
                        self._log.warning("scraper.job_save_error", error=str(exc))
                await db.commit()

            stats["jobs_found"] = len(jobs)
            stats["jobs_new"] = jobs_new
            self._log.info(
                "scraper.completed",
                jobs_found=len(jobs),
                jobs_new=jobs_new,
            )

        except Exception as exc:
            self._log.exception("scraper.failed", error=str(exc))
            stats["status"] = ScraperRunStatus.failed.value
            stats["error"] = str(exc)
            async with self.db_session_factory() as db:
                run_obj = await db.get(ScraperRun, run.id)
                if run_obj:
                    await finish_scraper_run(
                        db,
                        run_obj,
                        status=ScraperRunStatus.failed,
                        error_message=str(exc),
                    )
                    await db.commit()
            return stats

        async with self.db_session_factory() as db:
            run_obj = await db.get(ScraperRun, run.id)
            if run_obj:
                finished = await finish_scraper_run(
                    db,
                    run_obj,
                    status=ScraperRunStatus.completed,
                    jobs_found=stats["jobs_found"],
                    jobs_new=stats["jobs_new"],
                )
                await self._check_consecutive_zeros(finished)
            await db.commit()

        gc.collect()
        return stats

    # ------------------------------------------------------------------
    # Abstract interface
    # ------------------------------------------------------------------

    @abc.abstractmethod
    async def scrape(self) -> list[dict]:
        """Perform the actual scraping.  Return a list of raw job dicts."""

    # ------------------------------------------------------------------
    # Rate limiting
    # ------------------------------------------------------------------

    async def _rate_limit(self) -> None:
        """Sleep for a random duration within this site's configured rate limits."""
        low, high = RATE_LIMITS.get(
            self.site,
            (3.0, 8.0),
        )
        delay = random.uniform(low, high)
        self._log.debug("scraper.rate_limit", delay_seconds=round(delay, 2))
        await asyncio.sleep(delay)

    # ------------------------------------------------------------------
    # Structural hash check
    # ------------------------------------------------------------------

    async def _check_structural_hash(self, content: str, run: ScraperRun) -> bool:
        """Compute SHA-256 of *content* and compare to the previous run's hash.

        Returns True if the structure appears stable, False if a >30 % change
        is detected (which indicates a site layout change worth alerting on).
        """
        current_hash = hashlib.sha256(content.encode("utf-8", errors="replace")).hexdigest()

        async with self.db_session_factory() as db:
            latest = await get_latest_scraper_run(db, self.site)

        previous_hash: Optional[str] = None
        if latest and latest.id != run.id:
            previous_hash = latest.structure_hash

        # Store on the current run (will be persisted by caller)
        run.structure_hash = current_hash

        if previous_hash is None:
            self._log.debug("scraper.structure_hash_baseline", hash=current_hash[:16])
            return True

        # Simple Hamming-distance approximation by comparing hex nibbles
        if len(current_hash) == len(previous_hash):
            mismatches = sum(a != b for a, b in zip(current_hash, previous_hash))
            change_ratio = mismatches / len(current_hash)
        else:
            change_ratio = 1.0

        if change_ratio > 0.30:
            self._log.warning(
                "scraper.structure_changed",
                change_ratio=round(change_ratio, 3),
                previous_hash=previous_hash[:16],
                current_hash=current_hash[:16],
            )
            return False

        self._log.debug("scraper.structure_hash_ok", hash=current_hash[:16])
        return True

    # ------------------------------------------------------------------
    # Checkpoints
    # ------------------------------------------------------------------

    async def _save_checkpoint(self, run: ScraperRun, checkpoint: dict) -> None:
        """Persist *checkpoint* dict into ``scraper_runs.checkpoint_json``."""
        async with self.db_session_factory() as db:
            run_obj = await db.get(ScraperRun, run.id)
            if run_obj:
                run_obj.checkpoint_json = checkpoint
                await db.commit()
        self._log.debug("scraper.checkpoint_saved", keys=list(checkpoint.keys()))

    async def _load_checkpoint(self, site: str) -> Optional[dict]:
        """Load the checkpoint dict from the most recent scraper_run for *site*."""
        async with self.db_session_factory() as db:
            latest = await get_latest_scraper_run(db, site)
        if latest and latest.checkpoint_json:
            self._log.debug("scraper.checkpoint_loaded", site=site)
            return latest.checkpoint_json
        return None

    # ------------------------------------------------------------------
    # Deduplication
    # ------------------------------------------------------------------

    async def _dedup_job(self, db: Any, job_data: dict) -> tuple[Job, bool]:
        """Upsert a job and return (job, is_new).

        Expects job_data to contain at minimum:
          site, external_id, url, title, company
        """
        site = job_data.pop("site", self.site)
        external_id = job_data.pop("external_id")
        return await upsert_job(db, site=site, external_id=external_id, **job_data)

    # ------------------------------------------------------------------
    # Consecutive-zero guard
    # ------------------------------------------------------------------

    async def _check_consecutive_zeros(self, run: ScraperRun) -> None:
        """Warn loudly if this site has returned zero jobs several times in a row."""
        zeros = run.consecutive_zero_runs or 0
        threshold = 2
        if zeros >= threshold:
            self._log.warning(
                "scraper.consecutive_zeros",
                site=self.site,
                consecutive_zero_runs=zeros,
                action="manual inspection recommended",
            )
