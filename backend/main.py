"""FastAPI app — SSE hub + lifespan hooks."""
from __future__ import annotations

import asyncio
import gc
import json
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import AsyncGenerator, Optional

import psutil
import structlog
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession  # used in Depends(get_db) type hints

from backend.backup import run_backup
from backend.config import CV_MASTER_PATH, CV_SOURCES_DIR, settings
from backend.database.session import AsyncSessionLocal
from backend.database import get_db
from backend.database.crud import (
    count_applications_by_status,
    count_jobs_by_status,
    create_cv_source,
    delete_cv_source,
    get_application,
    get_cv_source,
    get_pending_reviews,
    get_setting,
    list_applications,
    list_company_sources,
    list_cv_sources,
    list_jobs,
    list_scraper_runs,
)
from backend.logging_config import setup_logging

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# SSE hub — broadcast events to all connected dashboard clients
# ---------------------------------------------------------------------------

class SSEHub:
    def __init__(self) -> None:
        self._clients: dict[str, asyncio.Queue] = {}

    def connect(self) -> tuple[str, asyncio.Queue]:
        client_id = str(uuid.uuid4())
        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._clients[client_id] = q
        log.info("sse.client_connected", client_id=client_id, total=len(self._clients))
        return client_id, q

    def disconnect(self, client_id: str) -> None:
        self._clients.pop(client_id, None)
        log.info("sse.client_disconnected", client_id=client_id, total=len(self._clients))

    async def broadcast(self, event: str, data: dict) -> None:
        payload = f"event: {event}\ndata: {json.dumps(data)}\n\n"
        dead: list[str] = []
        for cid, q in self._clients.items():
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                dead.append(cid)
        for cid in dead:
            self.disconnect(cid)

    async def stream(self, client_id: str, q: asyncio.Queue) -> AsyncGenerator[str, None]:
        try:
            yield ": connected\n\n"
            while True:
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=25.0)
                    yield msg
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
        finally:
            self.disconnect(client_id)


sse_hub = SSEHub()


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    log.info("jobbot.starting")

    # Run DB migrations
    from alembic.config import Config
    from alembic import command
    import asyncio

    def _run_migrations():
        alembic_cfg = Config("alembic.ini")
        command.upgrade(alembic_cfg, "head")

    await asyncio.get_event_loop().run_in_executor(None, _run_migrations)
    log.info("db.migrations_applied")

    # Startup backup
    try:
        await asyncio.get_event_loop().run_in_executor(None, run_backup)
    except Exception as exc:
        log.warning("startup.backup_failed", error=str(exc))

    # Auto-import legacy cv_master.pdf into cv_sources if table is empty
    try:
        import shutil as _shutil
        async with AsyncSessionLocal() as db:
            existing = await list_cv_sources(db)
            if not existing and CV_MASTER_PATH.exists():
                dest = CV_SOURCES_DIR / "1_cv_principal.pdf"
                _shutil.copy2(CV_MASTER_PATH, dest)
                await create_cv_source(
                    db,
                    name="CV Principal",
                    filename=CV_MASTER_PATH.name,
                    file_path=str(dest),
                )
                await db.commit()
                log.info("cv.legacy_imported", path=str(dest))
    except Exception as exc:
        log.warning("cv.legacy_import_failed", error=str(exc))

    # Start scheduler if setup complete
    if settings.setup_complete:
        from backend.scrapers.scheduler import start_scheduler
        start_scheduler()
        log.info("scheduler.started")

    yield

    # Shutdown
    log.info("jobbot.shutting_down")
    gc.collect()


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="JobBot API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# SSE endpoint
# ---------------------------------------------------------------------------

@app.get("/api/events")
async def event_stream(request: Request):
    client_id, q = sse_hub.connect()
    return StreamingResponse(
        sse_hub.stream(client_id, q),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/api/health")
async def health():
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    return {
        "status": "ok",
        "setup_complete": settings.setup_complete,
        "ram_total_gb": round(mem.total / 1e9, 1),
        "ram_available_gb": round(mem.available / 1e9, 1),
        "ram_percent": mem.percent,
        "disk_free_gb": round(disk.free / 1e9, 1),
        "ollama_host": settings.ollama_host,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------

@app.get("/api/jobs")
async def get_jobs(
    cursor: Optional[int] = Query(None),
    limit: int = Query(50, le=50),
    site: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    cv_profile: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    jobs, next_cursor = await list_jobs(
        db, cursor=cursor, limit=limit, site=site, status=status, cv_profile=cv_profile, search=search
    )
    return {
        "items": [_serialize_job(j) for j in jobs],
        "next_cursor": next_cursor,
    }


@app.get("/api/jobs/counts")
async def get_job_counts(db: AsyncSession = Depends(get_db)):
    return await count_jobs_by_status(db)


# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------

@app.get("/api/applications")
async def get_applications(
    cursor: Optional[int] = Query(None),
    limit: int = Query(50, le=50),
    status: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    apps, next_cursor = await list_applications(db, cursor=cursor, limit=limit, status=status)
    return {
        "items": [_serialize_application(a) for a in apps],
        "next_cursor": next_cursor,
    }


@app.get("/api/applications/counts")
async def get_application_counts(db: AsyncSession = Depends(get_db)):
    return await count_applications_by_status(db)


@app.get("/api/applications/pending-reviews")
async def get_pending_review_list(db: AsyncSession = Depends(get_db)):
    apps = await get_pending_reviews(db)
    return {"items": [_serialize_application(a) for a in apps], "count": len(apps)}


@app.post("/api/applications/{app_id}/authorize")
async def authorize_application(
    app_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Human confirms authorization to submit. Triggers actual form submission."""
    from backend.database.crud import get_application, transition_application
    from backend.database.models import ApplicationStatus

    app_obj = await get_application(db, app_id)
    if not app_obj:
        raise HTTPException(status_code=404, detail="Application not found")
    if app_obj.status != ApplicationStatus.pending_human_review.value:
        raise HTTPException(status_code=400, detail=f"Application is in status {app_obj.status}, not pending_human_review")

    # Mark authorized
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    app_obj = await transition_application(
        db, app_obj, ApplicationStatus.cv_approved,
        triggered_by="human",
        note="Human authorized submission",
        authorized_by_human=True,
        authorized_at=now,
    )

    # Fire submission in background
    asyncio.create_task(_submit_application(app_id))

    await sse_hub.broadcast("application_authorized", {"application_id": app_id})
    return {"status": "authorized", "application_id": app_id}


@app.post("/api/applications/{app_id}/reject")
async def reject_application(
    app_id: int,
    db: AsyncSession = Depends(get_db),
):
    from backend.database.crud import get_application, transition_application
    from backend.database.models import ApplicationStatus

    app_obj = await get_application(db, app_id)
    if not app_obj:
        raise HTTPException(status_code=404, detail="Application not found")
    app_obj = await transition_application(
        db, app_obj, ApplicationStatus.withdrawn,
        triggered_by="human",
        note="Human rejected in review",
    )
    await sse_hub.broadcast("application_rejected", {"application_id": app_id})
    return {"status": "withdrawn", "application_id": app_id}


# ---------------------------------------------------------------------------
# Scrapers
# ---------------------------------------------------------------------------

@app.get("/api/scrapers/status")
async def get_scraper_status(db: AsyncSession = Depends(get_db)):
    runs = await list_scraper_runs(db, limit=50)
    by_site: dict[str, dict] = {}
    for run in runs:
        if run.site not in by_site:
            by_site[run.site] = {
                "site": run.site,
                "last_run": run.started_at.isoformat() if run.started_at else None,
                "last_status": run.status,
                "jobs_found": run.jobs_found,
                "jobs_new": run.jobs_new,
                "consecutive_zero_runs": run.consecutive_zero_runs,
                "error_message": run.error_message,
            }
    return {"scrapers": list(by_site.values())}


@app.post("/api/scrapers/{site}/trigger")
async def trigger_scraper(site: str):
    """Manually trigger a scraper run."""
    asyncio.create_task(_run_scraper(site))
    return {"status": "triggered", "site": site, "task_id": str(uuid.uuid4())}


# ---------------------------------------------------------------------------
# CV
# ---------------------------------------------------------------------------

@app.post("/api/cv/generate/{application_id}")
async def generate_cv(application_id: int):
    task_id = str(uuid.uuid4())
    asyncio.create_task(_generate_cv_task(application_id, task_id))
    return {"status": "started", "task_id": task_id}


@app.get("/api/cv/sources")
async def get_cv_sources(db: AsyncSession = Depends(get_db)):
    sources = await list_cv_sources(db)
    return [
        {
            "id": s.id,
            "name": s.name,
            "filename": s.filename,
            "uploaded_at": s.uploaded_at.isoformat() if s.uploaded_at else None,
        }
        for s in sources
    ]


@app.delete("/api/cv/sources/{source_id}")
async def delete_cv_source_endpoint(source_id: int, db: AsyncSession = Depends(get_db)):
    from pathlib import Path as _Path
    source = await get_cv_source(db, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="CV source not found")
    file_path = _Path(source.file_path)
    await delete_cv_source(db, source_id)
    await db.commit()
    if file_path.exists():
        file_path.unlink()
    return {"status": "deleted", "id": source_id}


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

@app.get("/api/settings")
async def get_settings(db: AsyncSession = Depends(get_db)):
    from backend.database.crud import get_setting
    return {
        "ollama_host": await get_setting(db, "ollama_host", settings.ollama_host),
        "ollama_model": await get_setting(db, "ollama_model", settings.ollama_model),
        "sound_enabled": await get_setting(db, "sound_enabled", str(settings.sound_enabled)),
        "setup_complete": await get_setting(db, "setup_complete", "false"),
        "tos_accepted_at": await get_setting(db, "tos_accepted_at", ""),
    }


@app.post("/api/settings")
async def update_settings(body: dict, db: AsyncSession = Depends(get_db)):
    from backend.database.crud import set_setting
    for key, value in body.items():
        await set_setting(db, key, str(value))
    return {"status": "updated"}


# ---------------------------------------------------------------------------
# Company sources
# ---------------------------------------------------------------------------

@app.get("/api/company-sources")
async def get_company_sources(db: AsyncSession = Depends(get_db)):
    sources = await list_company_sources(db, enabled_only=False)
    return {"items": [_serialize_source(s) for s in sources]}


@app.post("/api/company-sources")
async def add_company_source(body: dict, db: AsyncSession = Depends(get_db)):
    from backend.database.crud import upsert_company_source
    source = await upsert_company_source(db, **body)
    return _serialize_source(source)


# ---------------------------------------------------------------------------
# First-run wizard
# ---------------------------------------------------------------------------

@app.get("/api/setup/status")
async def setup_status(db: AsyncSession = Depends(get_db)):
    from backend.first_run import get_wizard_status
    return await get_wizard_status(db)


@app.post("/api/setup/accept-tos")
async def accept_tos(db: AsyncSession = Depends(get_db)):
    from backend.database.crud import set_setting
    ts = datetime.now(timezone.utc).isoformat()
    await set_setting(db, "tos_accepted_at", ts)
    log.info("tos.accepted", timestamp=ts)
    return {"accepted_at": ts}


@app.post("/api/setup/complete")
async def complete_setup(db: AsyncSession = Depends(get_db)):
    from backend.database.crud import set_setting
    await set_setting(db, "setup_complete", "true")
    from backend.scrapers.scheduler import start_scheduler
    start_scheduler()
    return {"status": "complete"}


@app.post("/api/setup/upload-cv")
async def upload_cv(request: Request, db: AsyncSession = Depends(get_db)):
    """Accept CV PDF upload, save to data/cv_sources/, and create a CVSource record."""
    import re
    form = await request.form()
    file = form.get("file")
    if not file or not hasattr(file, "read"):
        raise HTTPException(status_code=400, detail="No file uploaded")
    original_filename = getattr(file, "filename", "cv.pdf")
    name_field = form.get("name", "")
    name = str(name_field).strip() if name_field else ""
    if not name:
        name = re.sub(r"\.(pdf)$", "", original_filename, flags=re.IGNORECASE) or "Mi CV"

    content = await file.read()
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower())[:40]

    # Determine unique filename
    existing_count = len(await list_cv_sources(db))
    dest_filename = f"{existing_count + 1}_{slug}.pdf"
    dest = CV_SOURCES_DIR / dest_filename
    dest.write_bytes(content)

    source = await create_cv_source(
        db, name=name, filename=original_filename, file_path=str(dest)
    )
    await db.commit()

    log.info("cv.uploaded", name=name, size_kb=len(content) // 1024, id=source.id)
    return {"status": "uploaded", "path": str(dest), "id": source.id, "name": source.name}


@app.post("/api/setup/pull-model")
async def pull_model(body: dict):
    """Pull an Ollama model and stream progress via SSE."""
    model = body.get("model", "")
    if not model:
        raise HTTPException(status_code=400, detail="model required")

    async def _pull():
        from backend.first_run import pull_model_with_progress
        async for chunk in pull_model_with_progress(model):
            await sse_hub.broadcast("model_pull_progress", {"model": model, **chunk})
        from backend.database.session import AsyncSessionLocal
        from backend.database.crud import set_setting
        async with AsyncSessionLocal() as db:
            await set_setting(db, "ollama_model", model)
            await db.commit()
        await sse_hub.broadcast("model_pull_complete", {"model": model})

    asyncio.create_task(_pull())
    return {"status": "started", "model": model}


@app.get("/api/setup/ollama-check")
async def ollama_check():
    """Return whether Ollama is installed and whether it's currently running."""
    from backend.first_run import get_ollama_check
    return await get_ollama_check()


@app.post("/api/setup/start-ollama")
async def start_ollama():
    """Attempt to launch 'ollama serve' in the background."""
    from backend.first_run import start_ollama_serve
    return await start_ollama_serve()


@app.post("/api/backup")
async def trigger_backup():
    """Manually trigger a database backup."""
    import asyncio
    dest = await asyncio.get_event_loop().run_in_executor(None, run_backup)
    return {"status": "complete", "path": str(dest)}


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------

@app.get("/api/notifications/queued")
async def get_queued_notifications():
    from backend.notifications.notifier import get_queued
    return {"items": get_queued()}


# ---------------------------------------------------------------------------
# Background task helpers
# ---------------------------------------------------------------------------

async def _run_scraper(site: str) -> None:
    try:
        from backend.scrapers.scheduler import run_scraper_by_name
        await run_scraper_by_name(site)
        await sse_hub.broadcast("scraper_finished", {"site": site})
    except Exception as exc:
        log.error("scraper.manual_trigger_failed", site=site, error=str(exc))
        await sse_hub.broadcast("scraper_error", {"site": site, "error": str(exc)})


async def _generate_cv_task(application_id: int, task_id: str) -> None:
    try:
        await sse_hub.broadcast("cv_generation_started", {
            "application_id": application_id, "task_id": task_id
        })
        from pathlib import Path as _Path
        from backend.ai.cv_adapter import adapt_cv
        from backend.documents.cv_parser import parse_cv

        async with AsyncSessionLocal() as db:
            app = await get_application(db, application_id)
            if not app:
                raise ValueError(f"Application {application_id} not found")

            # Resolve which CV source to use for this profile
            source_id_str = await get_setting(db, f"cv_source_{app.cv_profile}", None)
            if source_id_str:
                source = await get_cv_source(db, int(source_id_str))
                cv_path = _Path(source.file_path) if source else CV_MASTER_PATH
            else:
                # Fall back: pick first available cv_source, then cv_master.pdf
                sources = await list_cv_sources(db)
                cv_path = _Path(sources[0].file_path) if sources else CV_MASTER_PATH

            # Parse and store canonical JSON before adapt_cv runs
            canonical = await parse_cv(cv_path)
            app.cv_canonical_json = canonical
            await db.flush()
            await db.commit()

        async with AsyncSessionLocal() as db:
            result = await adapt_cv(db, application_id)

        await sse_hub.broadcast("cv_generation_complete", {
            "application_id": application_id,
            "task_id": task_id,
            "quality_score": result.get("quality_score"),
        })
    except Exception as exc:
        log.error("cv_generation.failed", application_id=application_id, error=str(exc))
        await sse_hub.broadcast("cv_generation_error", {
            "application_id": application_id, "error": str(exc)
        })


async def _submit_application(application_id: int) -> None:
    try:
        from backend.application.human_loop import submit_authorized
        async with AsyncSessionLocal() as db:
            result = await submit_authorized(db, application_id)
        await sse_hub.broadcast("application_submitted", {
            "application_id": application_id,
            "status": result.get("status"),
        })
    except Exception as exc:
        log.error("application.submit_failed", application_id=application_id, error=str(exc))


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

def _serialize_job(j) -> dict:
    return {
        "id": j.id,
        "site": j.site,
        "title": j.title,
        "company": j.company,
        "location": j.location,
        "url": j.url,
        "status": j.status,
        "cv_profile": j.cv_profile,
        "salary_raw": j.salary_raw,
        "contract_type": j.contract_type,
        "posted_at": j.posted_at.isoformat() if j.posted_at else None,
        "scraped_at": j.scraped_at.isoformat() if j.scraped_at else None,
    }


def _serialize_application(a) -> dict:
    return {
        "id": a.id,
        "job_id": a.job_id,
        "status": a.status,
        "cv_profile": a.cv_profile,
        "company": a.company,
        "quality_score": a.quality_score,
        "authorized_by_human": a.authorized_by_human,
        "authorized_at": a.authorized_at.isoformat() if a.authorized_at else None,
        "form_screenshot_path": a.form_screenshot_path,
        "form_url": a.form_url,
        "created_at": a.created_at.isoformat() if a.created_at else None,
        "updated_at": a.updated_at.isoformat() if a.updated_at else None,
    }


def _serialize_source(s) -> dict:
    return {
        "id": s.id,
        "company_name": s.company_name,
        "source_url": s.source_url,
        "scraper_type": s.scraper_type,
        "enabled": s.enabled,
        "cv_profile": s.cv_profile,
    }
