# currobot

Local-first job application automation for the Spanish job market.

Scrapes 14+ job boards, adapts your CV for each role using a local AI model, and submits applications — but only after you approve each one. Nothing leaves your machine.

---

## What it does

1. **Scrapes** InfoJobs, Indeed ES, Mercadona, Lidl, Amazon ES, Greenhouse, Lever, TeamTailor, Personio, Workday, Manfred, Tecnoempleo, JobToday, and custom career pages on a schedule
2. **Filters** jobs that explicitly disqualify for the student→work permit *canje* (temporal contracts, part-time, salary below SMI €15,876/year)
3. **Adapts your CV** using a local Ollama model — reframes your experience for each job profile (cashier, stocker, logistics, frontend dev, fullstack dev) without inventing anything
4. **Fills the application form** using browser automation with human-like behaviour
5. **Asks you to approve** — you see the filled form + adapted CV before anything is submitted. No submission happens without your click.

---

## For non-technical users

### What you need before starting

You need three things installed. All are free.

**1 — Python 3.11 or newer**

Check if you already have it:
```
python3 --version
```
If it says `Python 3.11.x` or higher, you're good. If not, download it from [python.org/downloads](https://www.python.org/downloads/) and run the installer.

**2 — Node.js**

Check:
```
node --version
```
If it says `v20.x.x` or higher, you're good. If not, download from [nodejs.org](https://nodejs.org) — pick the **LTS** version.

**3 — Ollama** (the local AI)

Download from [ollama.ai](https://ollama.ai) and install it like any Mac app. This is what runs the AI on your machine so your CV data never leaves it.

---

### Installation

**Step 1 — Download currobot**

Click the green **Code** button at the top of this page → **Download ZIP** → unzip it somewhere you'll remember (e.g. your Desktop or Documents folder).

Or if you know git:
```
git clone https://github.com/IFAKA/currobot.git
cd currobot
```

**Step 2 — Start it**

Open Terminal, navigate to the currobot folder, and run:
```
./start.sh
```

That's it. The script automatically:
- Creates a Python environment
- Installs all Python dependencies
- Installs the browser automation engine
- Installs frontend dependencies
- Starts the backend and the dashboard

**Step 3 — Open the dashboard**

Go to [http://localhost:3000](http://localhost:3000) in your browser.

The first time you open it, a **setup wizard** will guide you through:
- Checking your system (Python, Node, Ollama)
- Picking the right AI model for your RAM
- Downloading the model (one time, ~4 GB)
- Uploading your master CV as a PDF
- Accepting the terms

After that, you're in the dashboard. Scrapers run automatically in the background.

---

### Daily use

- **Dashboard** — system health, scraper status, application funnel
- **Jobs** — browse scraped jobs, filter by site or profile
- **Applications** — track everything from scraped to applied
- **Review** — jobs waiting for your approval before submission. You have 30 minutes per review before it expires.
- **CV** — manage your master CV
- **Settings** — change Ollama model, delays, notifications

### Stopping currobot

Press `Ctrl+C` in the Terminal window where you ran `./start.sh`.

### Auto-start on login (optional)

If you want currobot to start automatically when you log into your Mac:
```
./install_launchagent.sh
```

---

### What the filters do

currobot automatically skips jobs that explicitly disqualify for the Spanish student→work permit *canje* (Reglamento de Extranjería 2025):

| Disqualifier | Example |
|---|---|
| Temporal contract | "contrato temporal", "fijo discontinuo", "interinidad", "eventual", "por obra" |
| Part-time | "media jornada", "tiempo parcial", "20 horas semanales" |
| Salary below SMI | Any stated salary below €15,876/year or €1,134/month |

**If no contract type or salary is mentioned, the job passes through** — the filter only acts when something is explicitly disqualifying. Update `SMI_MONTHLY_GROSS` and `SMI_ANNUAL_GROSS` in `backend/scrapers/visa_filter.py` each January when the new SMI is published.

---

### Troubleshooting

**"python3 not found"** → Install Python from [python.org/downloads](https://www.python.org/downloads/)

**"node not found"** → Install Node.js LTS from [nodejs.org](https://nodejs.org)

**"Ollama not detected"** → Open a new Terminal and run `ollama serve`, then try `./start.sh` again

**Dashboard doesn't load** → Wait 10 seconds and refresh. The backend takes a moment on first start.

**Scraper returns zero jobs repeatedly** → A scraper disables itself after 5 consecutive empty runs. The site may have changed its layout. Check the logs in `data/logs/`.

---

## For developers

### Tech stack

| Layer | What |
|---|---|
| Backend | Python 3.11+, FastAPI, SQLAlchemy 2 (async), Alembic, aiosqlite |
| Scraping | Patchright (stealth Playwright), BeautifulSoup4, httpx |
| AI | Ollama (local LLM), custom 4-step CV adaptation pipeline |
| PDF | pdfplumber (parse), reportlab + weasyprint (generate) |
| Scheduling | APScheduler |
| Frontend | Next.js 16, React 19, Tailwind CSS 4, Radix UI |
| Real-time | Server-Sent Events (SSE) |
| macOS | Keychain via `keyring`, Launch Agent, `plyer` notifications |
| Tests | pytest |

### Project structure

```
currobot/
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
│   └── documents/
│       ├── cv_parser.py         # Parse PDF CV → canonical JSON
│       └── cv_generator.py      # Canonical JSON → adapted PDF
├── frontend/
│   ├── app/                     # Next.js App Router pages
│   ├── components/              # Sidebar, CommandPalette, UI primitives
│   └── lib/                    # API client, types, utilities
├── tests/
│   └── test_visa_filter.py      # 88 pytest cases for the visa filter
├── requirements.txt
├── start.sh                     # Single-command startup (handles venv + npm)
└── .env.example                 # Config reference
```

### Running locally

```bash
git clone https://github.com/IFAKA/currobot.git
cd currobot
./start.sh
```

### Running tests

```bash
# From project root
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
2. Add the profile config to `PROFILE_REFRAME` in `backend/ai/cv_adapter.py` — define `skills_emphasis`, `title_map`, and `role_context`
3. Run a database migration: `alembic revision --autogenerate -m "add profile"` + `alembic upgrade head`

### Configuration

Copy `.env.example` to `.env` and edit as needed. The defaults work out of the box.

```env
OLLAMA_HOST=http://localhost:11434   # change if Ollama runs on another machine
OLLAMA_MODEL=                        # leave empty for auto-selection by RAM
SCRAPER_DEFAULT_DELAY_MIN=3.0        # seconds between requests
SCRAPER_DEFAULT_DELAY_MAX=8.0
JOBS_RETENTION_DAYS=90
APPLICATIONS_RETENTION_DAYS=365
```

Credentials (job site logins) are stored in macOS Keychain via `keyring` — never in `.env`.

### Database

SQLite at `data/jobs.db`. Migrations with Alembic:

```bash
# Apply pending migrations
alembic upgrade head

# Create a new migration after model changes
alembic revision --autogenerate -m "description"
```

### Contributing

1. Fork the repo and create a branch: `git checkout -b feature/your-thing`
2. Make your changes
3. Run the tests: `python3 -m pytest tests/ -v`
4. Open a pull request — describe what you changed and why

All new logic with decision paths should have tests. The visa filter is a good example of the expected test structure.

---

## Uninstall

One command removes everything — the app, its data, the browser engine, the Launch Agent, and any Keychain entries:

```bash
./uninstall.sh
```

It will ask for confirmation twice (once before cleaning system files, once before deleting the project folder) and tell you exactly what it removes at each step.

---

## Privacy

- All CV data, job data, and application history stays on your machine in `data/`
- The AI runs locally via Ollama — no data is sent to any external service unless you point `OLLAMA_HOST` at a remote server
- Browser sessions and cookies are stored locally in `data/browser_profiles/`
- The `data/` directory is excluded from git

---

## License

MIT
