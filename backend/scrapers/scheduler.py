"""APScheduler integration — registers all scraper jobs on a per-site interval."""
from __future__ import annotations

import asyncio
from typing import Optional, TYPE_CHECKING

import structlog

from backend.config import DB_PATH

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Lazy imports of scraper classes (avoids circular imports at module level)
# ---------------------------------------------------------------------------

def _get_scraper_map() -> dict[str, type]:
    """Return a mapping of site name → scraper class.

    Imported lazily so that this module can be imported without triggering
    all heavy scraper dependencies at start-up.
    """
    from backend.scrapers.indeed_es import IndeedESScraper
    from backend.scrapers.infojobs import InfoJobsScraper
    from backend.scrapers.lidl_es import LidlESScraper
    from backend.scrapers.jobtoday import JobTodayScraper
    from backend.scrapers.mercadona import MercadonaScraper
    from backend.scrapers.amazon_es import AmazonESScraper
    from backend.scrapers.manfred import ManfredScraper
    from backend.scrapers.tecnoempleo import TecnoempleoScraper
    from backend.scrapers.greenhouse import GreenhouseScraper
    from backend.scrapers.lever import LeverScraper
    from backend.scrapers.teamtailor import TeamtailorScraper
    from backend.scrapers.personio import PersonioScraper
    from backend.scrapers.workday import WorkdayScraper
    from backend.scrapers.career_page import CareerPageScraper

    return {
        "indeed_es": IndeedESScraper,
        "infojobs": InfoJobsScraper,
        "lidl_es": LidlESScraper,
        "jobtoday": JobTodayScraper,
        "mercadona": MercadonaScraper,
        "amazon_es": AmazonESScraper,
        "manfred": ManfredScraper,
        "tecnoempleo": TecnoempleoScraper,
        "greenhouse": GreenhouseScraper,
        "lever": LeverScraper,
        "teamtailor": TeamtailorScraper,
        "personio": PersonioScraper,
        "workday": WorkdayScraper,
        "career_page": CareerPageScraper,
    }


# ---------------------------------------------------------------------------
# Scraper schedule — interval in hours per site
# ---------------------------------------------------------------------------

SCRAPER_SCHEDULE: dict[str, int] = {
    "indeed_es":    4,
    "infojobs":     4,
    "lidl_es":      6,
    "jobtoday":     3,
    "mercadona":    8,
    "amazon_es":   12,
    "manfred":      6,
    "tecnoempleo":  6,
    "greenhouse":   8,
    "lever":        8,
    "teamtailor":   8,
    "personio":     8,
    "workday":      8,
    "career_page": 12,
}

# ---------------------------------------------------------------------------
# Scheduler singleton
# ---------------------------------------------------------------------------

_scheduler: Optional[object] = None  # AsyncIOScheduler


def get_scheduler() -> Optional[object]:
    """Return the current scheduler instance (may be None before start_scheduler())."""
    return _scheduler


def start_scheduler() -> None:
    """Create and start the APScheduler AsyncIOScheduler.

    Uses a SQLAlchemyJobStore backed by the same jobs.db SQLite database so
    that scheduled job state survives restarts.
    """
    global _scheduler

    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
        from apscheduler.triggers.interval import IntervalTrigger
    except ImportError as exc:
        log.error(
            "scheduler.apscheduler_missing",
            error=str(exc),
            tip="pip install apscheduler sqlalchemy",
        )
        raise

    jobstore_url = f"sqlite:///{DB_PATH}"

    job_defaults = {
        "coalesce": True,
        "max_instances": 1,
        "misfire_grace_time": 600,  # 10 minutes grace on missed fires
    }

    scheduler = AsyncIOScheduler(
        jobstores={"default": SQLAlchemyJobStore(url=jobstore_url)},
        job_defaults=job_defaults,
        timezone="Europe/Madrid",
    )

    # Register a job for every site in the schedule
    scraper_map = _get_scraper_map()

    for site, interval_hours in SCRAPER_SCHEDULE.items():
        if site not in scraper_map:
            log.warning("scheduler.unknown_site", site=site)
            continue

        job_id = f"scraper_{site}"
        scheduler.add_job(
            run_scraper_by_name,
            trigger=IntervalTrigger(hours=interval_hours),
            id=job_id,
            name=f"Scraper: {site}",
            args=[site],
            replace_existing=True,
            coalesce=True,
            max_instances=1,
        )
        log.info(
            "scheduler.job_registered",
            site=site,
            interval_hours=interval_hours,
            job_id=job_id,
        )

    scheduler.start()
    _scheduler = scheduler
    log.info("scheduler.started", total_jobs=len(SCRAPER_SCHEDULE))


def stop_scheduler() -> None:
    """Gracefully shut down the scheduler."""
    global _scheduler
    if _scheduler is not None:
        try:
            _scheduler.shutdown(wait=True)  # type: ignore[union-attr]
            log.info("scheduler.stopped")
        except Exception as exc:
            log.warning("scheduler.stop_error", error=str(exc))
        finally:
            _scheduler = None


# ---------------------------------------------------------------------------
# Manual trigger
# ---------------------------------------------------------------------------

async def run_scraper_by_name(site: str) -> dict:
    """Instantiate and run a scraper by its site name.

    This is the async function called by APScheduler for each registered job.
    It can also be called directly from API endpoints for manual triggers.

    Returns the stats dict produced by BaseScraper.run().
    """
    scraper_map = _get_scraper_map()

    if site not in scraper_map:
        log.error("scheduler.unknown_scraper", site=site, known=list(scraper_map.keys()))
        return {"site": site, "error": "unknown scraper", "status": "failed"}

    from backend.database.session import AsyncSessionLocal

    scraper_cls = scraper_map[site]
    scraper = scraper_cls(db_session_factory=AsyncSessionLocal)

    log.info("scheduler.running_scraper", site=site, scraper=scraper_cls.__name__)

    try:
        stats = await scraper.run()
        log.info(
            "scheduler.scraper_finished",
            site=site,
            jobs_found=stats.get("jobs_found", 0),
            jobs_new=stats.get("jobs_new", 0),
            status=stats.get("status"),
        )
        return stats
    except Exception as exc:
        log.exception("scheduler.scraper_crashed", site=site, error=str(exc))
        return {"site": site, "error": str(exc), "status": "failed"}


async def run_all_scrapers_once() -> list[dict]:
    """Run all scrapers once sequentially.  Useful for initial seeding."""
    results: list[dict] = []
    for site in SCRAPER_SCHEDULE:
        log.info("scheduler.seeding", site=site)
        result = await run_scraper_by_name(site)
        results.append(result)
    return results
