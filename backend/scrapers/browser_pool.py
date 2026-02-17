"""Patchright (stealth Playwright) browser pool with cookie persistence."""
from __future__ import annotations

import asyncio
import gc
import json
import time
from pathlib import Path
from typing import Any, Optional

import structlog

try:
    from patchright.async_api import (
        async_playwright,
        BrowserContext,
        Playwright as AsyncPlaywright,
    )
    _PATCHRIGHT_AVAILABLE = True
except ImportError:
    try:
        from playwright.async_api import (  # type: ignore[no-redef]
            async_playwright,
            BrowserContext,
            Playwright as AsyncPlaywright,
        )
        _PATCHRIGHT_AVAILABLE = False
        structlog.get_logger(__name__).warning(
            "browser_pool.patchright_unavailable",
            fallback="playwright",
            note="Install patchright for better anti-bot evasion",
        )
    except ImportError as exc:
        raise ImportError(
            "Neither patchright nor playwright is installed. "
            "Run: pip install patchright"
        ) from exc

from backend.config import BROWSER_PROFILES_DIR, COOKIE_TTL, settings

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Realistic user agents (Chrome 124 on various platforms)
# ---------------------------------------------------------------------------

USER_AGENTS: list[str] = [
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_4) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
]


class BrowserPool:
    """Singleton-style pool that manages a single Chromium instance with
    per-site browser contexts.  Cookies are persisted to disk and reloaded
    on subsequent runs (respecting COOKIE_TTL per site).
    """

    _playwright: Optional[Any] = None          # AsyncPlaywright instance
    _browser: Optional[Any] = None             # Browser instance
    _contexts: dict[str, Any] = {}             # site → BrowserContext
    _lock: asyncio.Lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Context lifecycle
    # ------------------------------------------------------------------

    async def get_context(self, site: str) -> Any:
        """Return (or create) a BrowserContext for *site*."""
        async with self._lock:
            if site in self._contexts:
                return self._contexts[site]

            await self._ensure_browser()

            import random
            user_agent = random.choice(USER_AGENTS)

            context: Any = await self._browser.new_context(  # type: ignore[union-attr]
                user_agent=user_agent,
                locale="es-ES",
                timezone_id="Europe/Madrid",
                geolocation={"latitude": 40.4168, "longitude": -3.7038},
                permissions=["geolocation"],
                viewport={"width": 1366, "height": 768},
                color_scheme="light",
                extra_http_headers={
                    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
                },
            )

            # Inject stealth JS to mask automation signals
            await context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3]});
                Object.defineProperty(navigator, 'languages', {get: () => ['es-ES', 'es', 'en']});
                window.chrome = { runtime: {} };
            """)

            # Load saved cookies if not expired
            cookies_loaded = await self._load_cookies(site, context)
            if cookies_loaded:
                log.debug("browser_pool.cookies_loaded", site=site)
            else:
                log.debug("browser_pool.cookies_fresh", site=site)

            self._contexts[site] = context
            log.info("browser_pool.context_created", site=site)
            return context

    async def save_cookies(self, site: str, context: Any) -> None:
        """Persist cookies for *site* to disk."""
        cookies_dir = BROWSER_PROFILES_DIR / site
        cookies_dir.mkdir(parents=True, exist_ok=True)
        cookies_file = cookies_dir / "cookies.json"

        try:
            cookies = await context.cookies()
            payload = {
                "saved_at": time.time(),
                "cookies": cookies,
            }
            cookies_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            log.debug("browser_pool.cookies_saved", site=site, count=len(cookies))
        except Exception as exc:
            log.warning("browser_pool.cookies_save_error", site=site, error=str(exc))

    async def close_context(self, site: str) -> None:
        """Close and remove the context for *site*."""
        async with self._lock:
            ctx = self._contexts.pop(site, None)
            if ctx:
                try:
                    await ctx.close()
                    log.debug("browser_pool.context_closed", site=site)
                except Exception as exc:
                    log.warning("browser_pool.context_close_error", site=site, error=str(exc))
        gc.collect()

    async def close_all(self) -> None:
        """Close all contexts, the browser, and stop Playwright."""
        async with self._lock:
            for site, ctx in list(self._contexts.items()):
                try:
                    await ctx.close()
                    log.debug("browser_pool.context_closed", site=site)
                except Exception:
                    pass
            self._contexts.clear()

            if self._browser:
                try:
                    await self._browser.close()
                    log.debug("browser_pool.browser_closed")
                except Exception:
                    pass
                self._browser = None

            if self._playwright:
                try:
                    await self._playwright.stop()
                    log.debug("browser_pool.playwright_stopped")
                except Exception:
                    pass
                self._playwright = None

        gc.collect()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _ensure_browser(self) -> None:
        """Start Playwright + launch Chromium if not already running."""
        if self._playwright is None:
            self._playwright = await async_playwright().start()
            log.debug("browser_pool.playwright_started", engine="patchright" if _PATCHRIGHT_AVAILABLE else "playwright")

        if self._browser is None:
            self._browser = await self._playwright.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                    "--disable-infobars",
                    "--window-size=1366,768",
                    "--disable-extensions",
                    "--disable-gpu",
                    "--no-first-run",
                    "--no-default-browser-check",
                ],
            )
            log.debug("browser_pool.browser_launched")

    async def _load_cookies(self, site: str, context: Any) -> bool:
        """Load cookies from disk into *context* if they are not expired.

        Returns True if cookies were loaded, False otherwise.
        """
        cookies_file = BROWSER_PROFILES_DIR / site / "cookies.json"
        if not cookies_file.exists():
            return False

        try:
            payload = json.loads(cookies_file.read_text(encoding="utf-8"))
            saved_at: float = payload.get("saved_at", 0.0)
            cookies: list[dict] = payload.get("cookies", [])

            ttl_hours = COOKIE_TTL.get(site, 24)
            ttl_seconds = ttl_hours * 3600
            age_seconds = time.time() - saved_at

            if age_seconds > ttl_seconds:
                log.debug(
                    "browser_pool.cookies_expired",
                    site=site,
                    age_hours=round(age_seconds / 3600, 1),
                    ttl_hours=ttl_hours,
                )
                cookies_file.unlink(missing_ok=True)
                return False

            if cookies:
                await context.add_cookies(cookies)
                return True

        except Exception as exc:
            log.warning("browser_pool.cookies_load_error", site=site, error=str(exc))

        return False


# Module-level singleton
browser_pool = BrowserPool()
