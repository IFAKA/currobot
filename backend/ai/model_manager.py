"""RAM-aware single active model manager."""
from __future__ import annotations

import asyncio
import psutil
import structlog
import httpx
from backend.config import settings

log = structlog.get_logger(__name__)
_current_model: str = ""


async def get_recommended_model() -> str:
    ram_gb = psutil.virtual_memory().total / 1e9
    if ram_gb >= 32:
        return "mistral-nemo"
    elif ram_gb >= 16:
        return "qwen2.5:7b"
    else:
        return "llama3.1:8b"


async def get_active_model() -> str:
    global _current_model
    if not _current_model:
        _current_model = settings.ollama_model or await get_recommended_model()
    return _current_model


async def ensure_model_loaded(model: str) -> None:
    global _current_model
    ram = psutil.virtual_memory()
    if ram.available / 1e9 < 4:
        log.warning("model_manager.low_ram", available_gb=round(ram.available / 1e9, 1))
    if _current_model and _current_model != model:
        await unload_model(_current_model)
    _current_model = model
    log.info("model_manager.loaded", model=model)


async def unload_model(model: str) -> None:
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            await client.post(
                f"{settings.ollama_host}/api/generate",
                json={"model": model, "keep_alive": 0},
            )
        log.info("model_manager.unloaded", model=model)
    except Exception as e:
        log.warning("model_manager.unload_failed", model=model, error=str(e))
