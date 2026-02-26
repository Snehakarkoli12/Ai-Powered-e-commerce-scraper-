# -*- coding: utf-8 -*-
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.schemas import CompareRequest, CompareResponse, PipelineState
from app.agents.planner   import run_planner    # async def
from app.agents.scraper   import run_scraper    # async def
from app.agents.extractor import run_extractor  # async def
from app.agents.matcher   import run_matcher    # async def
from app.agents.ranker    import run_ranker     # def -- SYNC, no await
from app.agents.llm_ranker import llm_generate_explanation
from app.marketplaces.registry import marketplace_registry
from app.utils.llm_client import llm_client
from app.utils.logger import get_logger

logger = get_logger(__name__)


# ── Lifespan ──────────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("=== Startup: Agentic Price Browser (ScrapeGraphAI mode) ===")

    if not settings.groq_api_key:
        logger.error("GROQ_API_KEY is missing from .env — scraping will fail")
    else:
        logger.info("Groq API key detected ✓")

    try:
        if llm_client.enabled:
            logger.info(
                "LLM ready: primary=%s | fast=%s",
                llm_client.primary_model,
                llm_client.fast_model,
            )
        else:
            logger.warning("LLM disabled — set LLM_ENABLED=true in .env")
    except Exception as e:
        logger.error("LLM init error: %s", e)

    enabled = marketplace_registry.all_enabled()
    logger.info(
        "Marketplaces loaded: %d enabled — %s",
        len(enabled),
        [m.key for m in enabled],
    )

    yield

    logger.info("=== Shutdown ===")


# ── App ───────────────────────────────────────────────────────────────────────


app = FastAPI(
    title="Agentic Price Browser",
    description="AI-powered price comparison across Indian e-commerce marketplaces",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Pipeline helpers ──────────────────────────────────────────────────────────


def _make_state(request: CompareRequest) -> PipelineState:
    """
    Always constructs PipelineState without passing preferences= to __init__
    (avoids None validation error), then sets it via attribute assignment.
    """
    state = PipelineState(request=request)
    if request.preferences is not None:
        state.preferences = request.preferences
    return state


def _build_counts(state: PipelineState) -> dict:
    return {
        "raw_listings":      len(state.raw_listings),
        "normalized_offers": len(state.normalized_offers),
        "matched_offers":    len(state.matched_offers),
        "ranked_offers":     len(state.final_offers),
    }


# ── Pipeline runner ───────────────────────────────────────────────────────────


async def _run_pipeline(request: CompareRequest) -> PipelineState:
    state = _make_state(request)

    state = await run_planner(state)
    if not state.normalized_product:
        state.add_error("Planner: could not parse query into product attributes")
        return state
    logger.info(
        "Planner ✓ — '%s %s' | category=%s | sites=%d",
        state.normalized_product.attributes.brand or "",
        state.normalized_product.attributes.model or "",
        state.normalized_product.attributes.category,
        len(state.selected_marketplace_keys),
    )

    state = await run_scraper(state)
    logger.info("Scraper ✓ — raw_listings=%d", len(state.raw_listings))
    if not state.raw_listings:
        state.add_error("Scraper: 0 listings — check site_statuses for details")
        return state

    state = await run_extractor(state)
    logger.info("Extractor ✓ — normalized_offers=%d", len(state.normalized_offers))
    if not state.normalized_offers:
        state.add_error("Extractor: 0 offers normalized — prices may be unparseable")
        return state

    state = await run_matcher(state)
    logger.info("Matcher ✓ — matched_offers=%d", len(state.matched_offers))
    if not state.matched_offers:
        state.add_error("Matcher: 0 offers matched — try a broader query")
        return state

    # SYNC -- no await
    state = run_ranker(state)
    logger.info("Ranker done -- ranked_offers=%d", len(state.final_offers))

    # Generate LLM explanation (non-critical -- failure is OK)
    if state.final_offers:
        try:
            prefs = getattr(state, "preferences", None)
            mode = prefs.mode_enum() if prefs else None
            from app.schemas import RankingMode
            mode = mode or RankingMode.balanced
            query = state.normalized_product.search_query if state.normalized_product else ""
            explanation = await llm_generate_explanation(
                state.final_offers, mode, query
            )
            if explanation:
                state.explanation = explanation
                logger.info("Explanation generated: %s...", explanation[:80])
        except Exception as e:
            logger.warning("Explanation generation failed: %s", e)

    return state


# ── Routes ────────────────────────────────────────────────────────────────────


@app.get("/")
async def root():
    return {
        "name":    "Agentic Price Browser",
        "version": "2.0.0",
        "mode":    "ScrapeGraphAI + Groq",
        "docs":    "/docs",
        "health":  "/health",
    }


@app.get("/health")
async def health():
    enabled = marketplace_registry.all_enabled()
    return {
        "status":           "ok",
        "mode":             "ScrapeGraphAI + Groq",
        "llm_enabled":      llm_client.enabled,
        "llm_model":        llm_client.primary_model if llm_client.enabled else None,
        "groq_key_present": bool(settings.groq_api_key),
        "marketplaces":     [m.key for m in enabled],
        "total_markets":    len(enabled),
    }


@app.get("/api/marketplaces")
async def list_marketplaces():
    return {
        "marketplaces": [
            {
                "key":              m.key,
                "name":             m.name,
                "enabled":          m.enabled,
                "base_url":         m.base_url,
                "trust_score_base": m.trust_score_base,
            }
            for m in marketplace_registry.all()
        ]
    }


@app.get("/api/health/scrapers")
async def scraper_health():
    enabled = marketplace_registry.all_enabled()
    sites = [
        {
            "key":        m.key,
            "name":       m.name,
            "search_url": m.search_url_pattern.format(query="test"),
            "status":     "ready",
        }
        for m in enabled
    ]
    groq_ok = bool(settings.groq_api_key)
    return {
        "mode":             "ScrapeGraphAI + Groq",
        "llm_model":        llm_client.primary_model if llm_client.enabled else "disabled",
        "groq_key_present": groq_ok,
        "enabled_sites":    len(sites),
        "sites":            sites,
        "status":           "ready" if groq_ok else "ERROR: missing GROQ_API_KEY",
    }


@app.post("/api/compare", response_model=CompareResponse)
async def compare(request: CompareRequest):
    if not request.query and not request.product_url:
        raise HTTPException(
            status_code=400,
            detail="Provide at least one of: query, product_url",
        )

    start = time.time()

    try:
        state = await _run_pipeline(request)
    except Exception as exc:
        logger.exception("Unhandled pipeline error: %s", exc)
        raise HTTPException(status_code=500, detail=f"Pipeline error: {exc}") from exc

    return CompareResponse(
        query_time_seconds=round(time.time() - start, 3),
        normalized_product=state.normalized_product,
        selected_marketplaces=state.selected_marketplace_keys,
        counts=_build_counts(state),
        final_offers=state.final_offers,
        offers=state.final_offers,
        recommendation=state.final_offers[0] if state.final_offers else None,
        total_offers_found=len(state.final_offers),
        site_statuses=state.get_site_statuses_list(),
        explanation=state.explanation or "",
        errors=state.errors,
    )


@app.post("/api/debug/compare")
async def debug_compare(request: CompareRequest):
    """
    Extended debug endpoint — returns per-stage counts and all intermediate data.
    Never raises 500 — always returns whatever the pipeline produced before failure.
    """
    if not request.query and not request.product_url:
        raise HTTPException(
            status_code=400,
            detail="Provide at least one of: query, product_url",
        )

    start = time.time()
    state = _make_state(request)

    try:
        state = await run_planner(state)    # async
        state = await run_scraper(state)    # async
        state = await run_extractor(state)  # async
        state = await run_matcher(state)    # async
        state = run_ranker(state)           # SYNC — no await
    except Exception as exc:
        logger.exception("Debug pipeline error: %s", exc)
        return {
            "error":                 str(exc),
            "query_time_seconds":    round(time.time() - start, 3),
            "normalized_product":    state.normalized_product,
            "selected_marketplaces": state.selected_marketplace_keys,
            "counts":                _build_counts(state),
            "site_statuses":         state.get_site_statuses_list(),
            "errors":                state.errors,
        }

    return {
        "query_time_seconds":      round(time.time() - start, 3),
        "normalized_product":      state.normalized_product,
        "selected_marketplaces":   state.selected_marketplace_keys,
        "counts":                  _build_counts(state),
        "raw_listings":            state.raw_listings,
        "normalized_before_match": state.normalized_offers,
        "final_offers":            state.final_offers,
        "site_statuses":           state.get_site_statuses_list(),
        "errors":                  state.errors,
        "explanation":             state.explanation or "",
    }
