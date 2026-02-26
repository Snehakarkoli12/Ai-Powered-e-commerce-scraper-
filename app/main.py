import sys
if sys.platform == "win32":
    import asyncio
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())


import time
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.schemas import CompareRequest, CompareResponse
from app.agents import PipelineState
from app.agents.planner   import run_planner
from app.agents.scraper   import run_scraper
from app.agents.extractor import run_extractor
from app.agents.matcher   import run_matcher
from app.agents.ranker    import run_ranker
from app.marketplaces.registry import marketplace_registry
from app.scraping.playwright_manager import playwright_manager
from app.scraping.selector_engine    import selector_engine
from app.utils.llm_client            import llm_client
from app.utils.logger import get_logger

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("=== Startup ===")
    await playwright_manager.start()
    yield
    logger.info("=== Shutdown ===")
    await playwright_manager.stop()


app = FastAPI(
    title="Agentic Price Browser",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {
        "status":           "ok",
        "llm_enabled":      llm_client.enabled,
        "llm_model":        llm_client.primary_model,
        "marketplaces":     [m.key for m in marketplace_registry.all_enabled()],
        "playwright":       playwright_manager._browser is not None,
    }


@app.get("/api/marketplaces")
async def list_marketplaces():
    return {
        "marketplaces": [
            {"key": m.key, "name": m.name, "enabled": m.enabled,
             "trust_score": m.trust_score_base, "brand_affinity": m.brand_affinity}
            for m in marketplace_registry.all()
        ]
    }


@app.get("/api/selector-cache")
async def get_selector_cache():
    return selector_engine.dump_cache()


@app.get("/api/health/scrapers")
async def scraper_health():
    """
    Tests that every enabled marketplace scraper CAN be imported and instantiated.
    Does NOT run Playwright — purely checks Python imports.
    """
    import importlib
    results = {}
    for config in marketplace_registry.all_enabled():
        key         = config.key
        module_path = config.scraper_module or f"app.scraping.{key}"
        class_name  = "".join(p.capitalize() for p in key.split("_")) + "Scraper"
        try:
            mod   = importlib.import_module(module_path)
            klass = getattr(mod, class_name)
            _     = klass(config)   # instantiate
            results[key] = {"status": "ok", "module": module_path, "class": class_name}
        except Exception as e:
            results[key] = {
                "status": "error",
                "module": module_path,
                "class": class_name,
                "error": str(e),
            }
    ok    = sum(1 for v in results.values() if v["status"] == "ok")
    total = len(results)
    return {"importable": f"{ok}/{total}", "scrapers": results}



@app.post("/api/reload")
async def reload():
    marketplace_registry.reload()
    return {"status": "reloaded", "count": len(marketplace_registry.all_enabled())}


@app.post("/api/compare", response_model=CompareResponse)
async def compare(request: CompareRequest):
    if not request.query and not request.product_url:
        raise HTTPException(status_code=422, detail="Provide query or product_url")

    start = time.perf_counter()
    state = PipelineState(request=request)

    # Stage 1 — Planner (LLM query parsing)
    try:
        state = await run_planner(state)
        logger.info(f"[S1] product='{state.normalized_product.search_query}'")
    except Exception as e:
        logger.exception("Planner failed")
        raise HTTPException(status_code=422, detail=f"Planner: {e}")

    # Stage 2 — Scraper
    try:
        state = await run_scraper(state)
        logger.info(f"[S2] {len(state.raw_listings)} raw listings")
    except Exception as e:
        logger.exception("Scraper failed")
        state.add_error(f"Scraper: {e}")

    # Stage 3 — Extractor + LLM enrichment
    try:
        state = await run_extractor(state)
        logger.info(f"[S3] {len(state.normalized_offers)} normalized")
    except Exception as e:
        logger.exception("Extractor failed")
        state.add_error(f"Extractor: {e}")

    # Stage 4 — Matcher + LLM semantic scoring
    try:
        state = await run_matcher(state)
        logger.info(f"[S4] {len(state.matched_offers)} matched")
    except Exception as e:
        logger.exception("Matcher failed")
        state.add_error(f"Matcher: {e}")

    # Stage 5 — Ranker + LLM explanation
    try:
        state = await run_ranker(state)
        logger.info(f"[S5] {len(state.ranked_offers)} ranked")
    except Exception as e:
        logger.exception("Ranker failed")
        state.add_error(f"Ranker: {e}")

    elapsed = round(time.perf_counter() - start, 3)
    logger.info(f"Pipeline complete in {elapsed}s | offers={len(state.ranked_offers)}")

    return CompareResponse(
        normalized_product=state.normalized_product,
        offers=state.ranked_offers,
        recommendation=state.ranked_offers[0] if state.ranked_offers else None,
        explanation=state.explanation,
        site_statuses=state.get_site_statuses_list(),
        errors=state.errors,
        total_offers_found=len(state.ranked_offers),
        query_time_seconds=elapsed,
    )


@app.post("/api/debug/compare")
async def debug_compare(request: CompareRequest):
    """Full pipeline debug — exposes every intermediate state."""
    start = time.perf_counter()
    state = PipelineState(request=request)
    try: state = await run_planner(state)
    except Exception as e: return {"stage_failed": "planner", "error": str(e)}
    try: state = await run_scraper(state)
    except Exception as e: state.add_error(f"Scraper: {e}")
    try: state = await run_extractor(state)
    except Exception as e: state.add_error(f"Extractor: {e}")
    try: state = await run_matcher(state)
    except Exception as e: state.add_error(f"Matcher: {e}")
    try: state = await run_ranker(state)
    except Exception as e: state.add_error(f"Ranker: {e}")

    return {
        "query_time_seconds": round(time.perf_counter() - start, 3),
        "normalized_product": state.normalized_product.model_dump() if state.normalized_product else None,
        "selected_marketplaces": state.selected_marketplace_keys,
        "counts": {
            "raw_listings":      len(state.raw_listings),
            "normalized_offers": len(state.normalized_offers),
            "matched_offers":    len(state.matched_offers),
            "ranked_offers":     len(state.ranked_offers),
        },
        "raw_listings": [
            {"platform": r.platform_key, "title": r.title,
             "price": r.price_text, "url": (r.listing_url or "")[:80]}
            for r in state.raw_listings
        ],
        "normalized_before_match": [
            {"platform": o.platform_key, "title": o.title[:60],
             "effective_price": o.effective_price, "delivery_days": o.delivery_days_max}
            for o in state.normalized_offers
        ],
        "final_offers":   [o.model_dump() for o in state.ranked_offers],
        "site_statuses":  [s.model_dump() for s in state.get_site_statuses_list()],
        "errors":         state.errors,
        "selector_cache": selector_engine.dump_cache(),
    }
