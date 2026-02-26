from __future__ import annotations
from app.agents import PipelineState
from app.scraping.orchestrator import run_orchestrator
from app.marketplaces.registry import marketplace_registry
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def run_scraper(state: PipelineState) -> PipelineState:
    """Stage 2 — Playwright scraper across all selected marketplaces."""
    if not state.normalized_product:
        state.add_error("Scraper: no normalized_product — skipping")
        return state

    query     = state.normalized_product.search_query
    site_keys = state.selected_marketplace_keys

    # Fallback: if planner gave no keys, use all enabled
    if not site_keys:
        site_keys = [m.key for m in marketplace_registry.all_enabled()]
        logger.warning(f"No keys from planner — falling back to all: {site_keys}")
        state.selected_marketplace_keys = site_keys

    logger.info(f"Scraper: '{query}' across {len(site_keys)} sites: {site_keys}")

    listings, statuses, html_store = await run_orchestrator(
        search_query=query,
        marketplace_keys=site_keys,
        max_results_per_site=5,
    )

    state.raw_listings   = listings
    state.raw_html_store = html_store
    for s in statuses:
        state.set_site_status(s)

    ok    = [s for s in statuses if s.listings_found > 0]
    fails = [s for s in statuses if s.listings_found == 0]
    logger.info(f"  ✓ {len(ok)} sites with data: {[s.marketplace_key for s in ok]}")
    logger.info(f"  ✗ {len(fails)} sites empty:   {[(s.marketplace_key, s.status) for s in fails]}")

    if not listings:
        state.add_error(
            f"0 raw listings from {len(site_keys)} sites. "
            f"Check /api/health/scrapers for import errors."
        )
    return state
