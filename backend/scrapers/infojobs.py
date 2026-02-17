"""InfoJobs.net Tier 2 scraper — intercepts internal candidate/offer API calls."""
from __future__ import annotations

import asyncio
import json
from typing import Any, Optional
from urllib.parse import quote_plus

import structlog

from backend.scrapers.base import BaseScraper
from backend.scrapers.browser_pool import browser_pool

log = structlog.get_logger(__name__)

# Optional keyring for stored login credentials
try:
    import keyring as _keyring
    _KEYRING_AVAILABLE = True
except ImportError:
    _KEYRING_AVAILABLE = False


class InfoJobsScraper(BaseScraper):
    """Scrape InfoJobs by intercepting internal API JSON traffic."""

    SITE = "infojobs"

    SEARCH_QUERIES: list[str] = [
        "cajero",
        "reponedor",
        "mozo almacen",
        "dependiente",
        "frontend developer",
        "fullstack developer",
        "react developer",
    ]
    BASE_URL = "https://www.infojobs.net"

    def __init__(self, db_session_factory: Any) -> None:
        super().__init__(self.SITE, db_session_factory)

    # ------------------------------------------------------------------
    # Main scrape
    # ------------------------------------------------------------------

    async def scrape(self) -> list[dict]:
        context = await browser_pool.get_context(self.SITE)
        page = await context.new_page()
        all_jobs: list[dict] = []

        try:
            # Attempt login if credentials available
            await self._maybe_login(page)

            for query in self.SEARCH_QUERIES:
                self._log.info("infojobs.searching", query=query)
                jobs = await self._search_query(page, query)
                all_jobs.extend(jobs)
                self._log.info("infojobs.query_done", query=query, count=len(jobs))
                await self._rate_limit()

            await browser_pool.save_cookies(self.SITE, context)

        except Exception as exc:
            self._log.exception("infojobs.scrape_error", error=str(exc))
        finally:
            try:
                await page.close()
            except Exception:
                pass
            await browser_pool.close_context(self.SITE)

        self._log.info("infojobs.total", total=len(all_jobs))
        return all_jobs

    # ------------------------------------------------------------------
    # Login
    # ------------------------------------------------------------------

    async def _maybe_login(self, page: Any) -> None:
        """Attempt to log in with stored credentials if available."""
        if not _KEYRING_AVAILABLE:
            return

        try:
            username = _keyring.get_password("jobbot", "infojobs/username")
            password = _keyring.get_password("jobbot", "infojobs/password")
        except Exception:
            return

        if not username or not password:
            return

        try:
            self._log.info("infojobs.attempting_login", username=username)
            await page.goto(f"{self.BASE_URL}/candidate/login.xhtml", timeout=20_000, wait_until="domcontentloaded")
            await asyncio.sleep(1)

            email_sel = 'input[name="email"], input[type="email"], #email'
            pass_sel = 'input[name="password"], input[type="password"], #password'

            try:
                await page.fill(email_sel, username, timeout=5_000)
                await page.fill(pass_sel, password, timeout=5_000)
                await page.press(pass_sel, "Enter")
                await page.wait_for_load_state("networkidle", timeout=10_000)
                self._log.info("infojobs.login_submitted")
            except Exception as exc:
                self._log.warning("infojobs.login_form_error", error=str(exc))

        except Exception as exc:
            self._log.warning("infojobs.login_failed", error=str(exc))

    # ------------------------------------------------------------------
    # Per-query search
    # ------------------------------------------------------------------

    async def _search_query(self, page: Any, query: str) -> list[dict]:
        captured_jobs: list[dict] = []
        max_pages = 5

        async def handle_route(route: Any, request: Any) -> None:
            try:
                response = await route.fetch()
                body = await response.body()
                try:
                    data = json.loads(body)
                    self._extract_jobs_from_response(data, captured_jobs)
                except (json.JSONDecodeError, ValueError):
                    pass
                await route.fulfill(response=response)
            except Exception as exc:
                self._log.debug("infojobs.route_error", error=str(exc))
                try:
                    await route.continue_()
                except Exception:
                    pass

        # Intercept InfoJobs internal API endpoints
        await page.route("**/api/*/oferta/**", handle_route)
        await page.route("**/candidates-api/**", handle_route)
        await page.route("**/api/*/offer/**", handle_route)
        await page.route("**/jobad-search/**", handle_route)

        result: list[dict] = []
        seen: set[str] = set()

        for page_num in range(1, max_pages + 1):
            url = self._build_search_url(query, page_num)
            try:
                await page.goto(url, wait_until="networkidle", timeout=30_000)
                await asyncio.sleep(2)
            except Exception as exc:
                self._log.warning("infojobs.navigation_error", url=url, error=str(exc))
                break

            before = len(captured_jobs)
            await asyncio.sleep(1.5)
            after = len(captured_jobs)

            if after == before and page_num > 1:
                self._log.debug("infojobs.no_new_jobs", page=page_num)
                break

            await self._rate_limit()

        # Also try to extract from DOM as fallback
        dom_jobs = await self._extract_from_dom(page)
        captured_jobs.extend(dom_jobs)

        await page.unroute("**/api/*/oferta/**")
        await page.unroute("**/candidates-api/**")
        await page.unroute("**/api/*/offer/**")
        await page.unroute("**/jobad-search/**")

        for raw in captured_jobs:
            job = self._normalise_job(raw)
            if job and job["external_id"] not in seen:
                seen.add(job["external_id"])
                result.append(job)

        return result

    # ------------------------------------------------------------------
    # DOM fallback extraction
    # ------------------------------------------------------------------

    async def _extract_from_dom(self, page: Any) -> list[dict]:
        """Extract job cards from the DOM as a fallback."""
        jobs: list[dict] = []
        try:
            cards = await page.query_selector_all('[class*="ij-OfferCard"], [data-offer-id], .offer-item')
            for card in cards:
                try:
                    title_el = await card.query_selector('[class*="title"], h2, h3')
                    company_el = await card.query_selector('[class*="company"], [class*="employer"]')
                    location_el = await card.query_selector('[class*="location"], [class*="place"]')
                    link_el = await card.query_selector("a[href]")

                    title = await title_el.inner_text() if title_el else ""
                    company = await company_el.inner_text() if company_el else ""
                    location = await location_el.inner_text() if location_el else ""
                    href = await link_el.get_attribute("href") if link_el else ""

                    offer_id = await card.get_attribute("data-offer-id") or ""

                    if title or offer_id:
                        jobs.append({
                            "id": offer_id or href,
                            "title": title.strip(),
                            "company": {"name": company.strip()},
                            "location": {"label": location.strip()},
                            "detailUrl": (self.BASE_URL + href) if href and not href.startswith("http") else href,
                        })
                except Exception:
                    pass
        except Exception as exc:
            self._log.debug("infojobs.dom_extract_error", error=str(exc))
        return jobs

    # ------------------------------------------------------------------
    # Response extraction
    # ------------------------------------------------------------------

    def _extract_jobs_from_response(self, data: Any, out: list[dict]) -> None:
        if isinstance(data, dict):
            # Shape: {"items": [...]}
            for item in data.get("items", []):
                if isinstance(item, dict):
                    out.append(item)
            # Shape: {"offerList": [...]}
            for item in data.get("offerList", []):
                if isinstance(item, dict):
                    out.append(item)
            # Shape: {"offers": [...]}
            for item in data.get("offers", []):
                if isinstance(item, dict):
                    out.append(item)
            # Shape direct offer
            if "id" in data and "title" in data:
                out.append(data)
        elif isinstance(data, list):
            out.extend(item for item in data if isinstance(item, dict))

    # ------------------------------------------------------------------
    # Normalisation
    # ------------------------------------------------------------------

    def _normalise_job(self, raw: dict) -> Optional[dict]:
        external_id = str(raw.get("id") or raw.get("offerId") or raw.get("jobId") or "")
        if not external_id:
            return None

        title = raw.get("title") or raw.get("jobTitle") or ""
        company_node = raw.get("company") or {}
        company = (
            company_node.get("name") if isinstance(company_node, dict) else company_node
        ) or raw.get("companyName") or ""

        location_node = raw.get("location") or {}
        location = (
            location_node.get("label")
            if isinstance(location_node, dict)
            else location_node
        ) or raw.get("locationLabel") or ""

        salary_node = raw.get("salary") or {}
        if isinstance(salary_node, dict):
            salary_raw = salary_node.get("description") or salary_node.get("label")
        else:
            salary_raw = str(salary_node) if salary_node else None

        url = (
            raw.get("detailUrl")
            or raw.get("url")
            or (f"{self.BASE_URL}/oferta-empleo/{external_id}" if external_id else "")
        )
        if url and not url.startswith("http"):
            url = self.BASE_URL + url

        contract_type = (
            raw.get("contractType", {}).get("value")
            if isinstance(raw.get("contractType"), dict)
            else raw.get("contractType")
        )

        cv_profile = self._assign_cv_profile(title)

        return {
            "site": self.SITE,
            "external_id": external_id,
            "url": url,
            "title": title,
            "company": company,
            "location": location,
            "description": raw.get("description") or raw.get("snippet") or "",
            "salary_raw": salary_raw,
            "contract_type": contract_type,
            "cv_profile": cv_profile,
            "raw_data": raw,
        }

    # ------------------------------------------------------------------
    # URL builder
    # ------------------------------------------------------------------

    def _build_search_url(self, query: str, page: int = 1) -> str:
        q = quote_plus(query)
        return f"{self.BASE_URL}/jobsearch/searchResults/list.xhtml?keyword={q}&provinceIds=0&sortBy=PUBLICATION_DATE&page={page}"

    # ------------------------------------------------------------------
    # CV profile assignment
    # ------------------------------------------------------------------

    def _assign_cv_profile(self, title: str) -> str:
        t = title.lower()
        if any(kw in t for kw in ["react", "frontend", "front-end", "front end", "javascript", "typescript", "vue", "angular"]):
            return "frontend_dev"
        if any(kw in t for kw in ["fullstack", "full stack", "full-stack", "node", "backend", "python"]):
            return "fullstack_dev"
        if any(kw in t for kw in ["cajero", "cajera", "dependiente", "dependienta", "caja"]):
            return "cashier"
        if any(kw in t for kw in ["reponedor", "reponedora", "almacén", "almacen", "stock", "mozo"]):
            return "stocker"
        return "logistics"
