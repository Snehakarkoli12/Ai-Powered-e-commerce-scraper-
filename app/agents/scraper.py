# -*- coding: utf-8 -*-
from __future__ import annotations
from app.agents import PipelineState
from app.scraping.sgai_scraper import run_sgai_orchestrator
from app.marketplaces.registry import marketplace_registry
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def run_scraper(state: PipelineState) -> PipelineState:
    """Stage 2 — ScrapeGraphAI-powered scraper across all selected marketplaces."""
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
        "SGAI Scraper: '%s' across %d sites: %s",
        query, len(site_keys), site_keys,
    )

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
