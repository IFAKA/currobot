"""All DB writes go through here — single writer pattern."""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any, Optional, Sequence

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import (
    COMPANY_APPLICATION_RULES_DEFAULT_DAYS,
    COMPANY_APPLICATION_RULES_DEFAULT_MAX,
)
from backend.database.models import (
    Application,
    ApplicationEvent,
    ApplicationStatus,
    CompanyApplicationRule,
    CompanyBlocklist,
    CompanySource,
    CVDocument,
    Job,
    JobStatus,
    ScraperRun,
    ScraperRunStatus,
    Settings,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def make_external_id(site: str, title: str, company: str, location: str, date: str) -> str:
    """Synthetic dedup key when no platform ID is available."""
    raw = f"{site}|{title.lower()}|{company.lower()}|{location.lower()}|{date[:10]}"
    return hashlib.sha256(raw.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------

async def upsert_job(db: AsyncSession, *, site: str, external_id: str, **kwargs: Any) -> tuple[Job, bool]:
    """Insert-or-ignore on (site, external_id). Returns (job, is_new)."""
    result = await db.execute(
        select(Job).where(Job.site == site, Job.external_id == external_id)
    )
    existing = result.scalar_one_or_none()
    if existing:
        return existing, False
    job = Job(site=site, external_id=external_id, **kwargs)
    db.add(job)
    await db.flush()
    return job, True


async def get_job(db: AsyncSession, job_id: int) -> Optional[Job]:
    result = await db.execute(select(Job).where(Job.id == job_id))
    return result.scalar_one_or_none()


async def list_jobs(
    db: AsyncSession,
    *,
    cursor: Optional[int] = None,
    limit: int = 50,
    site: Optional[str] = None,
    status: Optional[str] = None,
    cv_profile: Optional[str] = None,
    search: Optional[str] = None,
) -> tuple[list[Job], Optional[int]]:
    q = select(Job).order_by(Job.id.desc())
    if cursor:
        q = q.where(Job.id < cursor)
    if site:
        q = q.where(Job.site == site)
    if status:
        q = q.where(Job.status == status)
    if cv_profile:
        q = q.where(Job.cv_profile == cv_profile)
    if search:
        term = f"%{search}%"
        q = q.where(Job.title.ilike(term) | Job.company.ilike(term))
    q = q.limit(limit + 1)
    result = await db.execute(q)
    rows = list(result.scalars().all())
    next_cursor = None
    if len(rows) > limit:
        rows = rows[:limit]
        next_cursor = rows[-1].id
    return rows, next_cursor


async def count_jobs_by_status(db: AsyncSession) -> dict[str, int]:
    result = await db.execute(
        select(Job.status, func.count(Job.id)).group_by(Job.status)
    )
    return {row[0]: row[1] for row in result.all()}


# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------

async def create_application(
    db: AsyncSession,
    *,
    job_id: int,
    cv_profile: str,
    company: str,
) -> Application:
    app = Application(
        job_id=job_id,
        cv_profile=cv_profile,
        company=company,
        status=ApplicationStatus.scraped.value,
    )
    db.add(app)
    await db.flush()
    await _log_event(db, application_id=app.id, old_status=None,
                     new_status=app.status, triggered_by="system")
    return app


async def transition_application(
    db: AsyncSession,
    application: Application,
    new_status: ApplicationStatus,
    triggered_by: str,
    note: Optional[str] = None,
    **extra_fields: Any,
) -> Application:
    old_status = application.status
    application.status = new_status.value
    application.updated_at = _now()
    for k, v in extra_fields.items():
        setattr(application, k, v)
    await db.flush()
    await _log_event(
        db,
        application_id=application.id,
        old_status=old_status,
        new_status=new_status.value,
        triggered_by=triggered_by,
        note=note,
    )
    return application


async def get_application(db: AsyncSession, app_id: int) -> Optional[Application]:
    result = await db.execute(
        select(Application).where(Application.id == app_id)
    )
    return result.scalar_one_or_none()


async def list_applications(
    db: AsyncSession,
    *,
    cursor: Optional[int] = None,
    limit: int = 50,
    status: Optional[str] = None,
) -> tuple[list[Application], Optional[int]]:
    q = select(Application).order_by(Application.id.desc())
    if cursor:
        q = q.where(Application.id < cursor)
    if status:
        q = q.where(Application.status == status)
    q = q.limit(limit + 1)
    result = await db.execute(q)
    rows = list(result.scalars().all())
    next_cursor = None
    if len(rows) > limit:
        rows = rows[:limit]
        next_cursor = rows[-1].id
    return rows, next_cursor


async def count_applications_by_status(db: AsyncSession) -> dict[str, int]:
    result = await db.execute(
        select(Application.status, func.count(Application.id)).group_by(Application.status)
    )
    return {row[0]: row[1] for row in result.all()}


async def get_pending_reviews(db: AsyncSession) -> list[Application]:
    result = await db.execute(
        select(Application)
        .where(Application.status == ApplicationStatus.pending_human_review.value)
        .order_by(Application.updated_at.asc())
    )
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Application event log
# ---------------------------------------------------------------------------

async def _log_event(
    db: AsyncSession,
    *,
    application_id: int,
    old_status: Optional[str],
    new_status: str,
    triggered_by: str,
    note: Optional[str] = None,
) -> ApplicationEvent:
    ev = ApplicationEvent(
        application_id=application_id,
        old_status=old_status,
        new_status=new_status,
        triggered_by=triggered_by,
        note=note,
    )
    db.add(ev)
    await db.flush()
    return ev


# ---------------------------------------------------------------------------
# Company blocklist
# ---------------------------------------------------------------------------

async def is_blocked(db: AsyncSession, company_name: str) -> bool:
    result = await db.execute(
        select(CompanyBlocklist).where(
            func.lower(CompanyBlocklist.company_name) == company_name.lower()
        )
    )
    return result.scalar_one_or_none() is not None


async def add_to_blocklist(
    db: AsyncSession, company_name: str, reason: Optional[str] = None
) -> CompanyBlocklist:
    entry = CompanyBlocklist(company_name=company_name, reason=reason)
    db.add(entry)
    await db.flush()
    return entry


async def list_blocklist(db: AsyncSession) -> list[CompanyBlocklist]:
    result = await db.execute(select(CompanyBlocklist).order_by(CompanyBlocklist.company_name))
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Company rate limits
# ---------------------------------------------------------------------------

async def check_company_rate_limit(db: AsyncSession, company: str) -> bool:
    """Returns True if we can apply (under limit), False if we should skip."""
    rule_result = await db.execute(
        select(CompanyApplicationRule).where(
            func.lower(CompanyApplicationRule.company_name) == company.lower()
        )
    )
    rule = rule_result.scalar_one_or_none()
    max_per_period = rule.max_per_period if rule else COMPANY_APPLICATION_RULES_DEFAULT_MAX
    period_days = rule.period_days if rule else COMPANY_APPLICATION_RULES_DEFAULT_DAYS

    cutoff = _now() - timedelta(days=period_days)
    count_result = await db.execute(
        select(func.count(Application.id))
        .join(Job)
        .where(
            func.lower(Application.company) == company.lower(),
            Application.status.notin_([
                ApplicationStatus.rejected.value,
                ApplicationStatus.withdrawn.value,
                ApplicationStatus.expired.value,
            ]),
            Application.created_at >= cutoff,
        )
    )
    count = count_result.scalar_one()
    return count < max_per_period


# ---------------------------------------------------------------------------
# Scraper runs
# ---------------------------------------------------------------------------

async def start_scraper_run(db: AsyncSession, site: str) -> ScraperRun:
    run = ScraperRun(site=site, status=ScraperRunStatus.running.value)
    db.add(run)
    await db.flush()
    return run


async def finish_scraper_run(
    db: AsyncSession,
    run: ScraperRun,
    *,
    status: ScraperRunStatus,
    jobs_found: int = 0,
    jobs_new: int = 0,
    structure_hash: Optional[str] = None,
    error_message: Optional[str] = None,
) -> ScraperRun:
    run.status = status.value
    run.finished_at = _now()
    run.jobs_found = jobs_found
    run.jobs_new = jobs_new
    if structure_hash:
        run.structure_hash = structure_hash
    if error_message:
        run.error_message = error_message

    # Track consecutive zero runs
    if jobs_found == 0 and status == ScraperRunStatus.completed:
        run.consecutive_zero_runs = (run.consecutive_zero_runs or 0) + 1
    else:
        run.consecutive_zero_runs = 0

    await db.flush()
    return run


async def get_latest_scraper_run(db: AsyncSession, site: str) -> Optional[ScraperRun]:
    result = await db.execute(
        select(ScraperRun)
        .where(ScraperRun.site == site)
        .order_by(ScraperRun.started_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def list_scraper_runs(db: AsyncSession, *, limit: int = 20) -> list[ScraperRun]:
    result = await db.execute(
        select(ScraperRun).order_by(ScraperRun.started_at.desc()).limit(limit)
    )
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Company sources
# ---------------------------------------------------------------------------

async def list_company_sources(db: AsyncSession, enabled_only: bool = True) -> list[CompanySource]:
    q = select(CompanySource)
    if enabled_only:
        q = q.where(CompanySource.enabled == True)
    result = await db.execute(q.order_by(CompanySource.company_name))
    return list(result.scalars().all())


async def upsert_company_source(
    db: AsyncSession, *, company_name: str, source_url: str, **kwargs: Any
) -> CompanySource:
    result = await db.execute(
        select(CompanySource).where(
            CompanySource.company_name == company_name,
            CompanySource.source_url == source_url,
        )
    )
    existing = result.scalar_one_or_none()
    if existing:
        for k, v in kwargs.items():
            setattr(existing, k, v)
        await db.flush()
        return existing
    source = CompanySource(company_name=company_name, source_url=source_url, **kwargs)
    db.add(source)
    await db.flush()
    return source


# ---------------------------------------------------------------------------
# Settings store
# ---------------------------------------------------------------------------

async def get_setting(db: AsyncSession, key: str, default: Optional[str] = None) -> Optional[str]:
    result = await db.execute(select(Settings).where(Settings.key == key))
    row = result.scalar_one_or_none()
    return row.value if row else default


async def set_setting(db: AsyncSession, key: str, value: str) -> Settings:
    result = await db.execute(select(Settings).where(Settings.key == key))
    row = result.scalar_one_or_none()
    if row:
        row.value = value
        await db.flush()
        return row
    row = Settings(key=key, value=value)
    db.add(row)
    await db.flush()
    return row


# ---------------------------------------------------------------------------
# Data retention cleanup
# ---------------------------------------------------------------------------

async def cleanup_old_records(
    db: AsyncSession,
    *,
    jobs_retention_days: int = 90,
    applications_retention_days: int = 365,
) -> dict[str, int]:
    jobs_cutoff = _now() - timedelta(days=jobs_retention_days)
    apps_cutoff = _now() - timedelta(days=applications_retention_days)

    # Only delete jobs that have no applications and are old
    jobs_result = await db.execute(
        delete(Job)
        .where(
            Job.scraped_at < jobs_cutoff,
            ~Job.id.in_(select(Application.job_id).distinct()),
        )
        .returning(Job.id)
    )
    jobs_deleted = len(jobs_result.fetchall())

    apps_result = await db.execute(
        delete(Application)
        .where(
            Application.created_at < apps_cutoff,
            Application.status.in_([
                ApplicationStatus.rejected.value,
                ApplicationStatus.withdrawn.value,
                ApplicationStatus.expired.value,
            ]),
        )
        .returning(Application.id)
    )
    apps_deleted = len(apps_result.fetchall())

    return {"jobs_deleted": jobs_deleted, "applications_deleted": apps_deleted}
