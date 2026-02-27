# -*- coding: utf-8 -*-
"""
Scraper agent — LangGraph node factory + backward-compatible runner.

The `make_scraper_node(site_key)` factory creates one LangGraph node function
per marketplace.  Each node:
  1. Checks if its site_key is in state["target_sites"] — skips if not.
  2. Dispatches to the appropriate scraper:
     - Amazon / Vijay Sales → Playwright + BeautifulSoup (Approach 2, NO LLM)
     - All others           → Playwright + Groq LLM 8B   (Approach 1)
  3. Returns {raw_results: [...], site_statuses: [status]}
     operator.add (via add_or_reset) merges across all parallel nodes.

All browser operations are guarded by a shared semaphore (max 3 concurrent).
"""
from __future__ import annotations
import asyncio
from typing import List, Tuple

from app.agents import PipelineState
from app.schemas import RawListing, SiteStatus, SiteStatusCode
from app.marketplaces.registry import marketplace_registry, MarketplaceConfig
from app.utils.logger import get_logger

logger = get_logger(__name__)


# ── Browser concurrency limiter ──────────────────────────────────────────────

_BROWSER_SEMAPHORE = None

def _get_browser_semaphore() -> asyncio.Semaphore:
    global _BROWSER_SEMAPHORE
    if _BROWSER_SEMAPHORE is None:
        _BROWSER_SEMAPHORE = asyncio.Semaphore(3)
    return _BROWSER_SEMAPHORE


# ── Dedicated (Approach 2) scraper lookup ────────────────────────────────────

_DEDICATED_SCRAPERS = {}
_APPROACH2_KEYS = {"amazon", "vijay_sales"}


def _get_dedicated_scraper(site_key: str):
    """Lazily instantiate dedicated BS4 scrapers (Approach 2 — no LLM)."""
    if site_key not in _DEDICATED_SCRAPERS:
        if site_key == "amazon":
            from app.scraping.amazon import AmazonScraper
            _DEDICATED_SCRAPERS[site_key] = AmazonScraper()
        elif site_key == "vijay_sales":
            from app.scraping.vijay_sales import VijaySalesScraper
            _DEDICATED_SCRAPERS[site_key] = VijaySalesScraper()
    return _DEDICATED_SCRAPERS.get(site_key)


# ═══════════════════════════════════════════════════════════════════════════════
# LangGraph node factory
# ═══════════════════════════════════════════════════════════════════════════════


def make_scraper_node(site_key: str):
    """Factory: creates a LangGraph async node function for a specific site.

    Each node checks target_sites FIRST (Constraint #11).
    If not in target_sites → returns empty results immediately.
    All browser operations use async/await (Constraint #12).
    """

    async def _scraper_node(state: dict) -> dict:
        target_sites = state.get("target_sites", [])

        # Constraint #11: check target_sites before scraping
        if site_key not in target_sites:
            return {"raw_results": [], "site_statuses": []}

        config = marketplace_registry.get(site_key)
        if not config or not config.enabled:
            return {"raw_results": [], "site_statuses": []}

        np = state.get("normalized_product")
        if not np:
            return {"raw_results": [], "site_statuses": []}

        query = np.search_query if hasattr(np, "search_query") else ""
        max_results = config.max_results

        logger.info("[%s] Scraper node starting: query='%s'", site_key, query[:60])

        sem = _get_browser_semaphore()
        async with sem:
            try:
                if site_key in _APPROACH2_KEYS:
                    # Approach 2: Playwright + BeautifulSoup (NO LLM)
                    scraper = _get_dedicated_scraper(site_key)
                    if scraper is None:
                        return {"raw_results": [], "site_statuses": [
                            SiteStatus(
                                marketplace_key=site_key,
                                marketplace_name=config.name,
                                status=SiteStatusCode.ERROR,
                                message=f"No dedicated scraper for {site_key}",
                            )
                        ]}
                    listings, site_status = await scraper.async_scrape(
                        query, max_results, site_key, config.name,
                    )
                else:
                    # Approach 1: Playwright + Groq LLM 8B
                    from app.scraping.sgai_scraper import scrape_one_site
                    listings, site_status = await scrape_one_site(
                        config, query, max_results,
                    )

                logger.info(
                    "[%s] Scraper node done: %d listings, status=%s",
                    site_key, len(listings), site_status.status.value,
                )
                return {
                    "raw_results": listings,
                    "site_statuses": [site_status],
                }

            except Exception as e:
                logger.error("[%s] Scraper node error: %s", site_key, str(e)[:120])
                return {
                    "raw_results": [],
                    "site_statuses": [SiteStatus(
                        marketplace_key=site_key,
                        marketplace_name=config.name,
                        status=SiteStatusCode.ERROR,
                        message=f"Error: {str(e)[:100]}",
                    )],
                }

    # Set a descriptive name for LangGraph node identification
    _scraper_node.__name__ = f"{site_key}_node"
    _scraper_node.__qualname__ = f"make_scraper_node.<locals>.{site_key}_node"

    return _scraper_node


# ═══════════════════════════════════════════════════════════════════════════════
# Backward-compatible runner (used by debug endpoint + old sequential pipeline)
# ═══════════════════════════════════════════════════════════════════════════════


async def run_scraper(state: PipelineState) -> PipelineState:
    """Stage 2 — Backward-compatible scraper across all selected marketplaces."""
    if not state.normalized_product:
        state.add_error("Scraper: no normalized_product — skipping")
        return state

    query     = state.normalized_product.search_query
    site_keys = state.selected_marketplace_keys

    if not site_keys:
        site_keys = [m.key for m in marketplace_registry.all_enabled()]
        logger.warning("No keys from planner — falling back to all: %s", site_keys)
        state.selected_marketplace_keys = site_keys

    logger.info(
        "Scraper: '%s' across %d sites: %s",
        query, len(site_keys), site_keys,
    )

    from app.scraping.sgai_scraper import run_sgai_orchestrator
    listings, statuses = await run_sgai_orchestrator(
        search_query=query,
        marketplace_keys=site_keys,
        max_results_per_site=5,
    )

    state.raw_listings = listings
    for s in statuses:
        state.set_site_status(s)

    ok    = [s for s in statuses if s.listings_found > 0]
    fails = [s for s in statuses if s.listings_found == 0]
    logger.info("  OK    (%d): %s", len(ok),    [s.marketplace_key for s in ok])
    logger.info("  FAIL  (%d): %s", len(fails), [(s.marketplace_key, s.status) for s in fails])

    if not listings:
        state.add_error(
            f"0 listings from {len(site_keys)} sites. "
            f"Failures: {[(s.marketplace_key, s.message[:60]) for s in fails[:4]]}"
        )
    return state
