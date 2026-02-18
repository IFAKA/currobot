# JobBot — build commands
#
# Dev:
#   make dev              → starts backend + frontend (no Tauri window)
#   make tauri-dev        → starts full Tauri app in dev mode
#
# Production:
#   make build            → full distributable (.app / .exe)
#
# Requirements:
#   Python 3.11+, Node.js 20+, Rust 1.70+, Ollama

SHELL := /bin/bash

.PHONY: dev tauri-dev build build-backend build-frontend clean

# ── Development ─────────────────────────────────────────────────────────────

dev:
	@echo "Starting backend..."
	@test -d .venv || python3.13 -m venv .venv
	@source .venv/bin/activate && pip install -q -r requirements.txt
	@source .venv/bin/activate && uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload &
	@echo "Starting frontend..."
	@cd frontend && npm install --silent && npm run dev

tauri-dev:
	@test -d .venv || python3.13 -m venv .venv
	@source .venv/bin/activate && pip install -q -r requirements.txt
	@source .venv/bin/activate && uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload &
	@cd frontend && npm install --silent && npm run tauri dev

# ── Production build ─────────────────────────────────────────────────────────

build: build-backend build-frontend
	@echo "Build complete. Distributable in frontend/src-tauri/target/release/bundle/"

build-backend:
	@echo "Building Python backend with PyInstaller..."
	@source .venv/bin/activate 2>/dev/null || (python3 -m venv .venv && source .venv/bin/activate && pip install -q -r requirements.txt pyinstaller)
	@source .venv/bin/activate && pip install -q pyinstaller
	@source .venv/bin/activate && pyinstaller backend.spec --distpath frontend/src-tauri/binaries/dist
	@TRIPLE=$$(rustc -vV | grep host | cut -d' ' -f2) && \
	  mv frontend/src-tauri/binaries/dist/jobbot-backend \
	     frontend/src-tauri/binaries/jobbot-backend-$$TRIPLE 2>/dev/null || \
	  mv frontend/src-tauri/binaries/dist/jobbot-backend.exe \
	     frontend/src-tauri/binaries/jobbot-backend-$$TRIPLE.exe 2>/dev/null
	@echo "Backend binary placed in frontend/src-tauri/binaries/"

build-frontend:
	@echo "Building Tauri app..."
	@cd frontend && npm install --silent && npm run tauri build

# ── Utilities ────────────────────────────────────────────────────────────────

clean:
	@rm -rf frontend/out frontend/.next
	@rm -rf frontend/src-tauri/target
	@rm -rf frontend/src-tauri/binaries/dist
	@rm -rf frontend/src-tauri/gen
	@rm -rf build dist __pycache__ .venv
	@echo "Cleaned."
