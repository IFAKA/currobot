"""Ollama HTTP client — timeout=120s, health check, restart on hang."""
from __future__ import annotations

import asyncio
import json
import subprocess
import time
from typing import Any, Optional

import httpx
import structlog
from backend.config import settings

log = structlog.get_logger(__name__)


async def health_check() -> bool:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{settings.ollama_host}/api/tags")
            return resp.status_code == 200
    except Exception:
        return False


async def generate(
    prompt: str,
    model: str,
    temperature: float = 0.3,
    format: Optional[dict] = None,
) -> str:
    payload: dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": temperature},
    }
    if format:
        payload["format"] = format

    for attempt in range(2):
        try:
            async with httpx.AsyncClient(timeout=settings.ollama_timeout) as client:
                resp = await client.post(
                    f"{settings.ollama_host}/api/generate", json=payload
                )
                resp.raise_for_status()
                data = resp.json()
                return data.get("response", "")
        except httpx.TimeoutException:
            log.warning("ollama_client.timeout", attempt=attempt, model=model)
            if attempt == 0:
                await _restart_ollama()
                await asyncio.sleep(5)
            else:
                raise
        except Exception as e:
            log.error("ollama_client.error", error=str(e), model=model)
            raise

    # Should not reach here, but satisfies type checker
    raise RuntimeError("generate: exhausted retries without returning")


async def generate_json(
    prompt: str,
    model: str,
    temperature: float = 0.3,
    schema: Optional[dict] = None,
) -> dict:
    result = await generate(prompt, model, temperature, format="json")
    try:
        # Find JSON object in response
        start = result.find("{")
        end = result.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(result[start:end])
        return json.loads(result)
    except json.JSONDecodeError as e:
        log.error(
            "ollama_client.json_decode_failed",
            error=str(e),
            response=result[:200],
        )
        raise


async def _restart_ollama() -> None:
    log.warning("ollama_client.restarting")
    try:
        subprocess.run(["pkill", "-f", "ollama serve"], capture_output=True)
        await asyncio.sleep(2)
        subprocess.Popen(
            ["ollama", "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        await asyncio.sleep(5)
        log.info("ollama_client.restarted")
    except Exception as e:
        log.error("ollama_client.restart_failed", error=str(e))
