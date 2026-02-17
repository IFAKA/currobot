#!/usr/bin/env bash
# JobBot — single command startup
# Usage: ./start.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── Colors ──────────────────────────────────────────────────────────────────
BLUE='\033[0;34m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info()    { echo -e "${BLUE}[jobbot]${NC} $*"; }
success() { echo -e "${GREEN}[jobbot]${NC} $*"; }
warn()    { echo -e "${YELLOW}[jobbot]${NC} $*"; }
error()   { echo -e "${RED}[jobbot]${NC} $*"; exit 1; }

# ── Requirements ─────────────────────────────────────────────────────────────
command -v python3 >/dev/null 2>&1 || error "python3 not found"
command -v node    >/dev/null 2>&1 || error "node not found"

# ── Ollama ───────────────────────────────────────────────────────────────────
if ! curl -sf http://localhost:11434/api/tags >/dev/null 2>&1; then
  info "Starting Ollama..."
  if command -v ollama >/dev/null 2>&1; then
    ollama serve &>/dev/null &
    OLLAMA_PID=$!
    sleep 3
    if ! curl -sf http://localhost:11434/api/tags >/dev/null 2>&1; then
      warn "Ollama did not start. CV generation will be unavailable."
    else
      success "Ollama started (pid $OLLAMA_PID)"
    fi
  else
    warn "ollama not found. Install from https://ollama.ai — CV generation will be unavailable."
  fi
else
  success "Ollama already running"
fi

# ── Python venv ──────────────────────────────────────────────────────────────
if [ ! -d ".venv" ]; then
  info "Creating Python virtual environment..."
  python3 -m venv .venv
fi
source .venv/bin/activate

if [ ! -f ".venv/.installed" ]; then
  info "Installing Python dependencies..."
  pip install -q -r requirements.txt
  touch .venv/.installed
  success "Python dependencies installed"
fi

# Install patchright browsers
if [ ! -f ".venv/.browsers" ]; then
  info "Installing Playwright browsers..."
  python -m patchright install chromium 2>/dev/null || python -m playwright install chromium
  touch .venv/.browsers
fi

# ── FastAPI backend ──────────────────────────────────────────────────────────
info "Starting FastAPI backend on http://localhost:8000..."
uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload &
BACKEND_PID=$!
sleep 2
if ! curl -sf http://localhost:8000/api/health >/dev/null 2>&1; then
  warn "Backend may not be ready yet — check logs"
else
  success "Backend running (pid $BACKEND_PID)"
fi

# ── Next.js frontend ─────────────────────────────────────────────────────────
if [ -d "frontend" ]; then
  info "Starting Next.js frontend on http://localhost:3000..."
  cd frontend
  if [ ! -d "node_modules" ]; then
    info "Installing frontend dependencies..."
    npm install
  fi
  npm run dev &
  FRONTEND_PID=$!
  cd ..
  success "Frontend starting (pid $FRONTEND_PID) — http://localhost:3000"
else
  warn "frontend/ directory not found — skipping"
fi

success "JobBot is running!"
echo ""
echo "  Dashboard: http://localhost:3000"
echo "  API:       http://localhost:8000"
echo "  API docs:  http://localhost:8000/docs"
echo ""
echo "  Press Ctrl+C to stop all services"

# ── Cleanup on exit ──────────────────────────────────────────────────────────
trap 'info "Shutting down..."; kill $BACKEND_PID 2>/dev/null || true; kill $FRONTEND_PID 2>/dev/null || true; exit 0' INT TERM

wait
