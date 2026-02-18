"""First-run wizard: system checks, model pull, CV setup, ToS."""
from __future__ import annotations

import asyncio
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

import httpx
import psutil
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import CV_MASTER_PATH, settings
from backend.database.crud import get_setting, list_cv_sources

log = structlog.get_logger(__name__)


async def get_wizard_status(db: AsyncSession) -> dict:
    """Return current completion state of each wizard step."""
    setup_complete = await get_setting(db, "setup_complete", "false")
    tos_accepted = await get_setting(db, "tos_accepted_at", "")
    ollama_model = await get_setting(db, "ollama_model", "")

    steps = {
        "system_check": await _check_system(),
        "ollama_running": await _check_ollama(),
        "model_downloaded": bool(ollama_model),
        "cv_uploaded": bool(await list_cv_sources(db)) or CV_MASTER_PATH.exists(),
        "tos_accepted": bool(tos_accepted),
        "setup_complete": setup_complete == "true",
    }
    steps["ready"] = all(steps.values())
    return steps


async def _check_system() -> bool:
    python_ok = sys.version_info >= (3, 11)
    node_ok = shutil.which("node") is not None
    return python_ok and node_ok


async def _check_ollama() -> bool:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{settings.ollama_host}/api/tags")
            return resp.status_code == 200
    except Exception:
        return False


def _ollama_binary_exists() -> bool:
    """Check if the ollama binary is installed on this system."""
    if shutil.which("ollama"):
        return True
    # Check common install locations in case PATH is incomplete
    common = [
        Path("/usr/local/bin/ollama"),
        Path("/opt/homebrew/bin/ollama"),
        Path.home() / ".ollama" / "ollama",
        Path("C:/Users") / "AppData" / "Local" / "Programs" / "Ollama" / "ollama.exe",
    ]
    return any(p.exists() for p in common)


async def get_ollama_check() -> dict:
    """Return whether Ollama is installed and whether it's currently running."""
    running = await _check_ollama()
    installed = running or _ollama_binary_exists()
    return {"installed": installed, "running": running}


async def start_ollama_serve() -> dict:
    """Attempt to launch 'ollama serve' in the background."""
    if await _check_ollama():
        return {"status": "already_running"}
    binary = shutil.which("ollama")
    if not binary:
        return {"status": "not_installed"}
    try:
        subprocess.Popen(
            [binary, "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return {"status": "starting"}
    except Exception as e:
        return {"status": "error", "detail": str(e)}


async def check_ram_and_recommend_model() -> dict:
    """Check available RAM and recommend the best Ollama model."""
    mem = psutil.virtual_memory()
    ram_gb = mem.total / 1e9

    if ram_gb >= 32:
        model = "mistral-nemo"
        reason = "32GB+ RAM — best Spanish quality"
    elif ram_gb >= 16:
        model = "qwen2.5:7b"
        reason = "16–32GB RAM — good Spanish, fits comfortably"
    else:
        model = "llama3.1:8b"
        reason = "< 16GB RAM — acceptable quality, extra validation enabled"

    return {
        "ram_gb": round(ram_gb, 1),
        "recommended_model": model,
        "reason": reason,
    }


async def pull_model_with_progress(model: str):  # type: ignore[return]
    """Stream model pull progress from Ollama API."""
    import json
    async with httpx.AsyncClient(timeout=600.0) as client:
        async with client.stream(
            "POST",
            f"{settings.ollama_host}/api/pull",
            json={"name": model, "stream": True},
        ) as resp:
            async for line in resp.aiter_lines():
                if line:
                    try:
                        yield json.loads(line)
                    except json.JSONDecodeError:
                        pass
