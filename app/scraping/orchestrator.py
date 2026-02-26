from __future__ import annotations
import asyncio
import importlib
from typing import List, Tuple, Dict, Optional

from app.marketplaces.registry import marketplace_registry
from app.schemas import RawListing, SiteStatus, SiteStatusCode
from app.utils.logger import get_logger

logger = get_logger(__name__)

# ── Lazy semaphore — created inside async context, not at module level ────────
_SEMAPHORE: Optional[asyncio.Semaphore] = None


def _get_semaphore() -> asyncio.Semaphore:
    global _SEMAPHORE
    if _SEMAPHORE is None:
        _SEMAPHORE = asyncio.Semaphore(4)
    return _SEMAPHORE


def _class_name(key: str) -> str:
    """jiomart → JiomartScraper | reliance_digital → RelianceDigitalScraper"""
    return "".join(p.capitalize() for p in key.split("_")) + "Scraper"


def _make_error_status(key: str, name: str, code: SiteStatusCode, msg: str) -> SiteStatus:
    return SiteStatus(
        marketplace_key=key,
        marketplace_name=name,
        status=code,
        message=msg,
        listings_found=0,
    )


async def _scrape_one(
    key: str, query: str, max_results: int
) -> Tuple[List[RawListing], SiteStatus, str]:
    """
    Always returns (listings, SiteStatus, raw_html).
    SiteStatus is NEVER None — failures produce an ERROR status.
    """
    config = marketplace_registry.get(key)
    if not config:
        return [], _make_error_status(
            key, key, SiteStatusCode.ERROR,
            f"Marketplace key '{key}' not found in registry"
        ), ""

    if not config.enabled:
        return [], _make_error_status(
            key, config.name, SiteStatusCode.ERROR,
            f"{config.name} is disabled"
        ), ""

    # ── Load scraper module ───────────────────────────────────────────────────
    module_path = config.scraper_module or f"app.scraping.{key}"
    class_name  = _class_name(key)

    try:
        mod    = importlib.import_module(module_path)
        klass  = getattr(mod, class_name)
        scraper = klass(config)
    except ImportError as e:
        msg = f"ImportError loading '{module_path}': {e}"
        logger.error(f"[{key}] {msg}")
        return [], _make_error_status(key, config.name, SiteStatusCode.ERROR, msg), ""
    except AttributeError as e:
        msg = f"Class '{class_name}' not found in '{module_path}': {e}"
        logger.error(f"[{key}] {msg}")
        return [], _make_error_status(key, config.name, SiteStatusCode.ERROR, msg), ""
    except Exception as e:
        msg = f"Failed to instantiate scraper: {e}"
        logger.error(f"[{key}] {msg}")
        return [], _make_error_status(key, config.name, SiteStatusCode.ERROR, msg), ""

    # ── Run scraper inside semaphore ──────────────────────────────────────────
    sem = _get_semaphore()
    async with sem:
        await asyncio.sleep(0.3)   # stagger requests
        try:
            listings, status, raw_html = await scraper.scrape(query, max_results)
            # Guarantee status is never None
            if status is None:
                status = _make_error_status(
                    key, config.name, SiteStatusCode.ERROR, "Scraper returned None status"
                )
            return listings, status, raw_html
        except Exception as e:
            msg = f"Scraper runtime error: {e}"
            logger.exception(f"[{key}] {msg}")
            return [], _make_error_status(key, config.name, SiteStatusCode.ERROR, msg), ""


async def run_orchestrator(
    search_query:         str,
    marketplace_keys:     List[str],
    max_results_per_site: int = 5,
) -> Tuple[List[RawListing], List[SiteStatus], Dict[str, str]]:

    logger.info(f"Orchestrator: query='{search_query}' | sites={marketplace_keys}")

    tasks   = [_scrape_one(k, search_query, max_results_per_site) for k in marketplace_keys]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    all_listings: List[RawListing]  = []
    all_statuses: List[SiteStatus]  = []
    html_store:   Dict[str, str]    = {}

    for i, result in enumerate(results):
        key = marketplace_keys[i] if i < len(marketplace_keys) else "unknown"

        if isinstance(result, Exception):
            logger.error(f"[{key}] gather exception: {result}")
            config = marketplace_registry.get(key)
            name   = config.name if config else key
            all_statuses.append(_make_error_status(
                key, name, SiteStatusCode.ERROR, f"Task exception: {result}"
            ))
            continue

        listings, status, raw_html = result
        if listings:
            all_listings.extend(listings)
        all_statuses.append(status)   # Always append — never filter by truthiness
        if raw_html:
            html_store[key] = raw_html

    ok_count = sum(1 for s in all_statuses if s.listings_found > 0)
    logger.info(
        f"Orchestrator done: {len(all_listings)} total listings | "
        f"{ok_count}/{len(all_statuses)} sites with results"
    )
    return all_listings, all_statuses, html_store
