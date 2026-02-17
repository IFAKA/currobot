# currobot

Local-first job application automation for the Spanish job market. Runs as a desktop app on macOS and Windows.

Scrapes 14+ job boards, adapts your CV for each role using a local AI model, and submits applications — but only after you approve each one. Nothing leaves your machine.

---

## What it does

1. **Scrapes** InfoJobs, Indeed ES, Mercadona, Lidl, Amazon ES, Greenhouse, Lever, TeamTailor, Personio, Workday, Manfred, Tecnoempleo, JobToday, and custom career pages on a schedule
2. **Filters** jobs that explicitly disqualify for the student→work permit *canje* (temporal contracts, part-time, salary below SMI €15,876/year)
3. **Adapts your CV** using a local Ollama model — reframes your experience for each job profile (cashier, stocker, logistics, frontend dev, fullstack dev) without inventing anything
4. **Fills the application form** using browser automation with human-like behaviour
5. **Asks you to approve** — you see the filled form + adapted CV before anything is submitted. No submission happens without your click.

---

## Install

Download the latest release for your platform from the [Releases page](../../releases):

- **macOS** — `.dmg` → drag currobot to Applications
- **Windows** — `.msi` → run the installer

**Before launching, install Ollama** (the local AI runtime):
Download from [ollama.ai](https://ollama.ai) and run it. currobot uses it to adapt your CV locally — no data leaves your device.

---

## First launch

The first time you open currobot, a **setup wizard** guides you through:

1. System check (Ollama running, enough disk space)
2. RAM check + AI model recommendation
3. Download the Ollama model (one-time, ~4 GB)
4. Upload your master CV as a PDF
5. Accept the terms
6. Choose whether to start currobot on login

After that you're in the dashboard. The Python backend and scrapers run automatically in the background.

---

## Daily use

currobot lives in the **system tray**. Close the window and it keeps running. Click the tray icon to reopen.

| Page | What it does |
|---|---|
| Dashboard | System health, scraper status, application funnel |
| Jobs | Browse scraped jobs, filter by site or profile |
| Applications | Kanban board — from scraped to applied |
| Review | Approve pending applications before submission (30-min window) |
| CV | Manage your master CV |
| Settings | Ollama model, retention, company sources, start-on-login toggle |

**Tray menu:**
- **Open currobot** — bring the window to front
- **Start on Login** — toggle autolaunch (checkmark = enabled)
- **Uninstall currobot…** — disables autolaunch then quits; then delete the app manually

---

## Uninstall

**Step 1 — disable autolaunch** (skip if you never enabled it):
Right-click the tray icon → **Uninstall currobot…** — this disables the login item and quits the app.

**Step 2 — remove the app:**
- macOS: move `currobot.app` from Applications to Trash
- Windows: Settings → Add or Remove Programs → currobot → Uninstall

**Step 3 — remove app data (optional):**
- macOS: `~/Library/Application Support/com.currobot.app/`
- Windows: `%APPDATA%\com.currobot.app\`

**Step 4 — remove Keychain entries (optional):**
- macOS: open Keychain Access, search "currobot", delete matching entries
- Windows: open Credential Manager, remove "currobot" entries

---

## What the filters do

currobot automatically skips jobs that explicitly disqualify for the Spanish student→work permit *canje* (Reglamento de Extranjería 2025):

| Disqualifier | Example |
|---|---|
| Temporal contract | "contrato temporal", "fijo discontinuo", "interinidad", "eventual", "por obra" |
| Part-time | "media jornada", "tiempo parcial", "20 horas semanales" |
| Salary below SMI | Any stated salary below €15,876/year or €1,134/month |

**If no contract type or salary is mentioned, the job passes through** — the filter only acts when something is explicitly disqualifying. Update `SMI_MONTHLY_GROSS` and `SMI_ANNUAL_GROSS` in `backend/scrapers/visa_filter.py` each January when the new SMI is published.

---

## For developers

### Tech stack

| Layer | What |
|---|---|
| Desktop shell | Tauri v2 (Rust) — tray, window, autolaunch, notifications |
| Backend | Python 3.11+, FastAPI, SQLAlchemy 2 (async), aiosqlite |
| Scraping | Patchright (stealth Playwright), BeautifulSoup4, httpx |
| AI | Ollama (local LLM), custom 4-step CV adaptation pipeline |
| PDF | pdfplumber (parse), reportlab + weasyprint (generate) |
| Scheduling | APScheduler |
| Frontend | Next.js 16 (static export), React 19, Tailwind CSS 4, Radix UI |
| Real-time | Server-Sent Events (SSE) |
| Credentials | `keyring` (macOS Keychain / Windows Credential Manager / Linux Secret Service) |
| Tests | pytest |

### Project structure

```
jobbot/
├── backend/
│   ├── main.py                  # FastAPI app, all REST + SSE endpoints
│   ├── config.py                # Central config, rate limits, data paths
│   ├── database/
│   │   ├── models.py            # SQLAlchemy ORM models + status enums
│   │   ├── crud.py              # All DB writes (single-writer pattern)
│   │   ├── session.py           # AsyncSessionLocal factory
│   │   └── alembic/             # Migrations
│   ├── scrapers/
│   │   ├── base.py              # BaseScraper — all scrapers inherit this
│   │   ├── visa_filter.py       # Canje eligibility filter (contract/salary/hours)
│   │   ├── scheduler.py         # APScheduler job registration
│   │   ├── browser_pool.py      # Shared Playwright contexts + cookie persistence
│   │   └── *.py                 # 14 site-specific scrapers
│   ├── ai/
│   │   ├── cv_adapter.py        # 4-step CV adaptation pipeline
│   │   ├── ollama_client.py     # HTTP client to Ollama
│   │   ├── prompts.py           # All LLM prompt templates (versioned)
│   │   ├── quality_check.py     # Score adapted CV against job description
│   │   └── validator.py         # Anti-fabrication checks
│   ├── application/
│   │   ├── form_detector.py     # Detect and classify form fields
│   │   ├── form_filler.py       # Fill fields with semantic mapping (ES/EN)
│   │   ├── confirm_detector.py  # Detect confirmation screens post-submit
│   │   └── human_loop.py        # Prepare review, auth flow, 30-min timeout
│   ├── notifications/
│   │   └── notifier.py          # In-memory notification queue (SSE → Tauri)
│   └── documents/
│       ├── cv_parser.py         # Parse PDF CV → canonical JSON
│       └── cv_generator.py      # Canonical JSON → adapted PDF
├── frontend/
│   ├── app/                     # Next.js App Router pages
│   ├── components/              # Sidebar, CommandPalette, UI primitives
│   ├── lib/                     # API client, types, utilities
│   └── src-tauri/               # Tauri desktop shell (Rust)
│       ├── src/lib.rs           # Tray, window, sidecar, autolaunch logic
│       ├── tauri.conf.json      # App config, bundle settings
│       └── capabilities/        # Tauri v2 permission definitions
├── tests/
│   └── test_visa_filter.py      # 88 pytest cases for the visa filter
├── backend.spec                 # PyInstaller spec (bundles backend into binary)
├── Makefile                     # Build pipeline
├── requirements.txt
└── .env.example                 # Config reference
```

### Running in development

```bash
# Option 1 — backend + Next.js dev server (no native window)
make dev

# Option 2 — full Tauri desktop window
make tauri-dev
```

`make dev` requires Python 3.11+ and Node 20+ installed locally. Ollama must be running.

### Building a distributable

```bash
make build
```

This runs PyInstaller to bundle the Python backend, then `tauri build` to produce the platform installer (`.dmg` on macOS, `.msi` on Windows).

### Running tests

```bash
python3 -m pytest tests/ -v
```

Currently tested: `visa_filter.py` (88 cases covering contract type, part-time, salary parsing, edge cases, and combined scenarios).

### Adding a scraper

1. Create `backend/scrapers/yoursite.py` — inherit from `BaseScraper`, implement `scrape() -> list[dict]`
2. Each job dict must include: `external_id`, `url`, `title`, `company`. Optional: `location`, `description`, `salary_raw`, `contract_type`, `cv_profile`
3. Register it in `backend/scrapers/scheduler.py` → `_get_scraper_map()`
4. Add its rate limit to `RATE_LIMITS` in `backend/config.py`

The base class handles: deduplication, visa filter, rate limiting, consecutive-zero guard, scraper run logging, and SSE broadcast.

### Adding a CV profile

1. Add the enum value to `CVProfile` in `backend/database/models.py`
2. Add the profile config to `PROFILE_REFRAME` in `backend/ai/cv_adapter.py`
3. Run a database migration: `alembic revision --autogenerate -m "add profile"` + `alembic upgrade head`

### Configuration

Copy `.env.example` to `.env` and edit as needed:

```env
OLLAMA_HOST=http://localhost:11434   # change if Ollama runs on another machine
OLLAMA_MODEL=                        # leave empty for auto-selection by RAM
SCRAPER_DEFAULT_DELAY_MIN=3.0
SCRAPER_DEFAULT_DELAY_MAX=8.0
JOBS_RETENTION_DAYS=90
APPLICATIONS_RETENTION_DAYS=365
```

Credentials (job site logins) are stored in the OS keychain via `keyring` — never in `.env`.

### Database

SQLite at `data/jobs.db`. Migrations with Alembic:

```bash
alembic upgrade head
alembic revision --autogenerate -m "description"
```

---

## Privacy

- All CV data, job data, and application history stays on your machine in `data/`
- The AI runs locally via Ollama — no data is sent to any external service unless you point `OLLAMA_HOST` at a remote server
- Browser sessions and cookies are stored locally in `data/browser_profiles/`
- The `data/` directory is excluded from git

---

## License

MIT
