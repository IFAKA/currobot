# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**currobot** is a local-first desktop app for job application automation in the Spanish job market. It scrapes 14+ job boards, adapts CVs using local AI (Ollama), and submits applications — all with mandatory human review before submission. No data leaves the device.

## Commands

### Development

```bash
make dev          # Start backend (uvicorn :8000) + Next.js dev server (no Tauri window)
make tauri-dev    # Full Tauri desktop app in dev mode (requires backend running separately)
```

### Building

```bash
make build-backend   # PyInstaller → bundles Python backend to frontend/src-tauri/binaries/
make build-frontend  # Tauri build → generates .dmg (macOS) or .msi (Windows)
make build           # Full production distributable
make clean           # Remove build artifacts, .venv, cache
```

### Testing

```bash
python3 -m pytest tests/ -v          # Run all tests
python3 -m pytest tests/test_visa_filter.py -v  # Run a single test file
```

### Frontend (from `frontend/` directory)

```bash
npm run dev       # Next.js dev server on :3000
npm run build     # Static export to frontend/out/
npm run lint      # ESLint
```

## Architecture

The app has three runtime layers:

1. **Tauri shell** (`frontend/src-tauri/`) — Rust-based desktop shell handling tray icon, window management, autolaunch, and sidecar lifecycle for the Python backend
2. **FastAPI backend** (`backend/`) — All business logic served on `localhost:8000`; real-time updates via SSE at `/api/events`
3. **Next.js frontend** (`frontend/app/`) — Static export (`out/`), loaded by Tauri; communicates exclusively with the local FastAPI backend

### Backend structure (`backend/`)

| Module | Purpose |
|--------|---------|
| `main.py` | All REST + SSE endpoints |
| `config.py` | Central settings, paths, retention policies |
| `database/` | SQLAlchemy 2 models, CRUD, async sessions (aiosqlite), Alembic migrations |
| `scrapers/` | 14 site-specific scrapers + base class, visa filter, browser pool, APScheduler |
| `ai/` | Ollama client, 4-step CV adapter pipeline, quality checks, model manager |
| `application/` | Patchright form detection, semantic filling, confirmation, human review loop |
| `documents/` | CV parser (PDF→JSON via pdfplumber) and generator (JSON→PDF via ReportLab/WeasyPrint) |
| `security/` | `keyring` integration for macOS Keychain / Windows Credential Manager |
| `notifications/` | In-memory SSE notification queue |

### Frontend structure (`frontend/`)

| Directory | Purpose |
|-----------|---------|
| `app/` | Next.js App Router pages: dashboard, jobs, applications, review, cv, settings, setup |
| `components/` | Sidebar, CommandPalette, Radix UI-based components |
| `lib/api.ts` | All backend API calls |
| `lib/types.ts` | Shared TypeScript types |

### Data flow

- Scrapers run on APScheduler schedule and write to SQLite (`data/jobs.db`)
- Visa filter (`backend/scrapers/visa_filter.py`) enforces Spanish employment law constraints
- CV adaptation: `documents/` parses master CV → `ai/` sends to Ollama → generates adapted PDF
- All applications require human authorization via `/api/applications/{id}/authorize` before Patchright submits the form

### Key configuration

- **Environment**: Copy `.env.example` → `.env` at project root; backend reads from there via `config.py`
- **Tauri**: `frontend/src-tauri/tauri.conf.json` — `externalBin` points to the PyInstaller-bundled backend sidecar
- **Database migrations**: `alembic.ini` at root, versions in `backend/database/alembic/versions/`
- **Ollama**: Backend auto-selects model based on available RAM; configurable via `OLLAMA_MODEL` env var

### CI/CD

GitHub Actions in `.github/workflows/release.yml` builds macOS + Windows distributable on push. The workflow uses `tauri-action` and packages the PyInstaller binary alongside the Tauri bundle.
