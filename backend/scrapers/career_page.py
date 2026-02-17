"""Generic configurable career page scraper — reads company_sources from DB."""
from __future__ import annotations

import asyncio
import hashlib
from typing import Any, Optional
from urllib.parse import urljoin

import structlog

from backend.scrapers.base import BaseScraper
from backend.scrapers.browser_pool import browser_pool

log = structlog.get_logger(__name__)

# Fallback selectors to try when no css_selector is configured
FALLBACK_SELECTORS = [
    "[class*='job']",
    "[class*='position']",
    "[class*='vacancy']",
    "[class*='opening']",
    "[class*='career']",
    "[class*='role']",
    "article",
    "li[class]",
]


class CareerPageScraper(BaseScraper):
    """Scrape arbitrary company career pages using browser automation.

    Reads configured sources from ``company_sources`` where
    ``scraper_type = 'career_page'``.  Each source can optionally specify a
    ``css_selector`` (stored in ``CompanySource.css_selector``) to target the
    job listing elements precisely.
    """

    SITE = "career_page"

    def __init__(self, db_session_factory: Any) -> None:
        super().__init__(self.SITE, db_session_factory)

    # ------------------------------------------------------------------
    # Main scrape
    # ------------------------------------------------------------------

    async def scrape(self) -> list[dict]:
        # Load company sources from DB
        sources = []
        try:
            async with self.db_session_factory() as db:
                from backend.database.crud import list_company_sources
                all_sources = await list_company_sources(db, enabled_only=True)
                sources = [s for s in all_sources if s.scraper_type == "career_page"]
        except Exception as exc:
            self._log.warning("career_page.db_error", error=str(exc))
            return []

        if not sources:
            self._log.info("career_page.no_sources_configured")
            return []

        all_jobs: list[dict] = []

        for source in sources:
            self._log.info(
                "career_page.scraping_source",
                company=source.company_name,
                url=source.source_url,
            )
            try:
                jobs = await self._scrape_source(source)
                all_jobs.extend(jobs)
                self._log.info(
                    "career_page.source_done",
                    company=source.company_name,
                    found=len(jobs),
                )
            except Exception as exc:
                self._log.warning(
                    "career_page.source_error",
                    company=source.company_name,
                    error=str(exc),
                )
            await self._rate_limit()

        # Deduplicate
        seen: set[str] = set()
        unique: list[dict] = []
        for job in all_jobs:
            eid = job.get("external_id", "")
            if eid not in seen:
                seen.add(eid)
                unique.append(job)

        self._log.info("career_page.total", total=len(unique))
        return unique

    # ------------------------------------------------------------------
    # Per-source scrape
    # ------------------------------------------------------------------

    async def _scrape_source(self, source: Any) -> list[dict]:
        site_key = f"career_page_{source.company_name.lower().replace(' ', '_')}"
        context = await browser_pool.get_context(site_key)
        page = await context.new_page()
        jobs: list[dict] = []

        try:
            # Navigate to the career page and wait for it to settle
            await page.goto(source.source_url, wait_until="networkidle", timeout=45_000)
            await asyncio.sleep(2)

            # Scroll to trigger lazy loading
            try:
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await asyncio.sleep(1)
                await page.evaluate("window.scrollTo(0, 0)")
            except Exception:
                pass

            # Find job elements
            elements = await self._find_job_elements(page, source.css_selector)

            if not elements:
                self._log.warning(
                    "career_page.no_elements_found",
                    company=source.company_name,
                    url=source.source_url,
                )
                return []

            # Extract basic info from listing page
            listing_jobs = await self._extract_from_elements(elements, source)
            jobs.extend(listing_jobs)

            # Optionally navigate to each job detail page for more info
            # (only if we have a reasonable number of jobs to avoid infinite scraping)
            if len(listing_jobs) <= 30:
                detailed_jobs = await self._enrich_with_detail_pages(listing_jobs, source, page)
                jobs = detailed_jobs
            else:
                jobs = listing_jobs

        except Exception as exc:
            self._log.exception(
                "career_page.page_error",
                company=source.company_name,
                error=str(exc),
            )
        finally:
            try:
                await page.close()
            except Exception:
                pass
            try:
                await browser_pool.close_context(site_key)
            except Exception:
                pass

        return jobs

    # ------------------------------------------------------------------
    # Element finding
    # ------------------------------------------------------------------

    async def _find_job_elements(self, page: Any, css_selector: Optional[str]) -> list[Any]:
        """Return a list of page elements representing job listings."""
        # Try configured selector first
        if css_selector:
            try:
                elements = await page.query_selector_all(css_selector)
                if elements:
                    self._log.debug("career_page.selector_hit", selector=css_selector, count=len(elements))
                    return elements
                else:
                    self._log.debug("career_page.selector_empty", selector=css_selector)
            except Exception as exc:
                self._log.debug("career_page.selector_error", selector=css_selector, error=str(exc))

        # Try fallback selectors
        for selector in FALLBACK_SELECTORS:
            try:
                elements = await page.query_selector_all(selector)
                if len(elements) >= 3:
                    # Sanity check: must look like job cards (have text, have links)
                    sample = elements[:5]
                    has_links = False
                    for el in sample:
                        link = await el.query_selector("a")
                        if link:
                            has_links = True
                            break
                    if has_links:
                        self._log.debug("career_page.fallback_selector_hit", selector=selector, count=len(elements))
                        return elements
            except Exception:
                continue

        return []

    # ------------------------------------------------------------------
    # Extraction
    # ------------------------------------------------------------------

    async def _extract_from_elements(self, elements: list[Any], source: Any) -> list[dict]:
        jobs: list[dict] = []
        base_url = source.source_url

        for element in elements:
            try:
                # Title: inner text of heading or the element itself
                title = ""
                title_el = await element.query_selector("h1, h2, h3, h4, h5, [class*='title'], [class*='name']")
                if title_el:
                    title = (await title_el.inner_text()).strip()
                else:
                    # Try link text
                    link_el = await element.query_selector("a")
                    if link_el:
                        title = (await link_el.inner_text()).strip()
                    else:
                        raw_text = (await element.inner_text()).strip()
                        # Take first line as title
                        title = raw_text.split("\n")[0][:120].strip()

                if not title or len(title) < 4:
                    continue

                # URL: find first link
                href = ""
                link_el = await element.query_selector("a[href]")
                if link_el:
                    href = await link_el.get_attribute("href") or ""
                    if href and not href.startswith("http"):
                        href = urljoin(base_url, href)

                # Location
                location = "España"
                loc_el = await element.query_selector(
                    "[class*='location'], [class*='place'], [class*='city'], [class*='lugar']"
                )
                if loc_el:
                    location = (await loc_el.inner_text()).strip() or "España"

                external_id = self._extract_id_from_url(href) or self._synthetic_id(
                    title, source.company_name
                )

                jobs.append({
                    "site": self.SITE,
                    "external_id": f"{source.company_name.lower().replace(' ', '_')}_{external_id}",
                    "url": href or base_url,
                    "title": title,
                    "company": source.company_name,
                    "location": location,
                    "description": None,
                    "salary_raw": None,
                    "contract_type": None,
                    "cv_profile": source.cv_profile,
                    "raw_data": {"title": title, "url": href},
                })

            except Exception as exc:
                self._log.debug("career_page.element_extract_error", error=str(exc))
                continue

        return jobs

    # ------------------------------------------------------------------
    # Detail page enrichment
    # ------------------------------------------------------------------

    async def _enrich_with_detail_pages(
        self, jobs: list[dict], source: Any, page: Any
    ) -> list[dict]:
        """Visit each job URL to extract a richer description."""
        enriched: list[dict] = []

        for job in jobs:
            url = job.get("url", "")
            if not url or url == source.source_url:
                enriched.append(job)
                continue

            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=20_000)
                await asyncio.sleep(1)

                # Try to grab the main content block
                description = ""
                for sel in [
                    "[class*='description']",
                    "[class*='content']",
                    "main",
                    "article",
                    ".job-detail",
                ]:
                    content_el = await page.query_selector(sel)
                    if content_el:
                        description = (await content_el.inner_text()).strip()[:3000]
                        break

                if description:
                    job["description"] = description

                enriched.append(job)
                await self._rate_limit()

            except Exception as exc:
                self._log.debug("career_page.detail_page_error", url=url, error=str(exc))
                enriched.append(job)

        return enriched

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _extract_id_from_url(self, url: str) -> str:
        if not url:
            return ""
        from urllib.parse import urlparse
        path = urlparse(url).path
        parts = [p for p in path.split("/") if p]
        return parts[-1] if parts else ""

    def _synthetic_id(self, title: str, company: str) -> str:
        raw = f"{self.SITE}|{company.lower()}|{title.lower()}"
        return hashlib.sha256(raw.encode()).hexdigest()[:32]
