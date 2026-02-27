# -*- coding: utf-8 -*-
"""
FastAPI application — LangGraph-powered price comparison pipeline.

Endpoints:
  POST /api/compare       → SSE streaming (master prompt spec)
  POST /api/compare/sync  → JSON response (backward-compatible)
  POST /api/debug/compare → JSON debug with all intermediate data
  GET  /                  → Service info
  GET  /health            → Health check
  GET  /api/marketplaces  → List all marketplaces
"""
import json
import time
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import StreamingResponse

from app.config import settings
from app.schemas import (
    CompareRequest, CompareResponse, PipelineState,
    NormalizedOffer, SiteStatus, RankingMode,
)
from app.chatbot.schemas import ChatRequest as ChatRequest
from app.marketplaces.registry import marketplace_registry
from app.utils.llm_client import llm_client
from app.utils.logger import get_logger

logger = get_logger(__name__)


# ── Optional: Redis caching ──────────────────────────────────────────────────

_redis_client = None

try:
    import redis.asyncio as aioredis
    _REDIS_AVAILABLE = True
except ImportError:
    _REDIS_AVAILABLE = False


async def _get_redis():
    """Get async Redis client (lazy init). Returns None if unavailable."""
    global _redis_client
    if not _REDIS_AVAILABLE:
        return None
    url = getattr(settings, "redis_url", None) or ""
    if not url.strip():
        return None
    if _redis_client is None:
        try:
            _redis_client = aioredis.from_url(url, decode_responses=True)
            await _redis_client.ping()
            logger.info("Redis connected: %s", url[:40])
        except Exception as e:
            logger.warning("Redis unavailable: %s", str(e)[:80])
            _redis_client = None
    return _redis_client


async def _get_cache(query: str, mode: str) -> Optional[dict]:
    """Check Redis cache. Key = f"{query}:{mode}", TTL = 5 min."""
    r = await _get_redis()
    if not r:
        return None
    try:
        key = f"compare:{query}:{mode}"
        cached = await r.get(key)
        if cached:
            logger.info("Cache HIT: %s", key[:60])
            return json.loads(cached)
    except Exception as e:
        logger.warning("Cache get error: %s", str(e)[:60])
    return None


async def _set_cache(query: str, mode: str, data: dict):
    """Store in Redis with 5 min TTL."""
    r = await _get_redis()
    if not r:
        return
    try:
        key = f"compare:{query}:{mode}"
        await r.set(key, json.dumps(data, default=str), ex=300)
        logger.info("Cache SET: %s (TTL=300s)", key[:60])
    except Exception as e:
        logger.warning("Cache set error: %s", str(e)[:60])


# ── Optional: PostgreSQL price history ───────────────────────────────────────

_pg_pool = None

try:
    import asyncpg
    _PG_AVAILABLE = True
except ImportError:
    _PG_AVAILABLE = False


async def _init_pg():
    """Initialize PostgreSQL connection pool and create table if needed."""
    global _pg_pool
    if not _PG_AVAILABLE:
        return
    url = getattr(settings, "database_url", None) or ""
    if not url.strip():
        return
    try:
        _pg_pool = await asyncpg.create_pool(url, min_size=1, max_size=5)
        async with _pg_pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS price_history (
                    id SERIAL PRIMARY KEY,
                    query TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    site TEXT NOT NULL,
                    title TEXT,
                    price DOUBLE PRECISION,
                    rating DOUBLE PRECISION,
                    url TEXT,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """)
        logger.info("PostgreSQL connected and price_history table ready")
    except Exception as e:
        logger.warning("PostgreSQL unavailable: %s", str(e)[:80])
        _pg_pool = None


async def _log_prices(query: str, mode: str, offers: list):
    """Store price entries in PostgreSQL price_history table."""
    if not _pg_pool:
        return
    try:
        async with _pg_pool.acquire() as conn:
            for o in offers[:10]:
                await conn.execute(
                    "INSERT INTO price_history (query, mode, site, title, price, rating, url) "
                    "VALUES ($1, $2, $3, $4, $5, $6, $7)",
                    query, mode,
                    getattr(o, "platform_key", "") or getattr(o, "site", ""),
                    getattr(o, "title", ""),
                    getattr(o, "effective_price", None),
                    getattr(o, "seller_rating", None) or getattr(o, "rating", None),
                    getattr(o, "listing_url", "") or getattr(o, "url", ""),
                )
        logger.info("Logged %d prices to PostgreSQL", min(len(offers), 10))
    except Exception as e:
        logger.warning("PostgreSQL log error: %s", str(e)[:80])


# ── Lifespan ──────────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("=== Startup: AI Price Comparison (LangGraph mode) ===")

    if not settings.groq_api_key:
        logger.error("GROQ_API_KEY is missing from .env — pipeline will fail")
    else:
        logger.info("Groq API key detected ✓")

    try:
        if llm_client.enabled:
            logger.info(
                "LLM ready: primary=%s | fast=%s",
                llm_client.primary_model, llm_client.fast_model,
            )
    except Exception as e:
        logger.error("LLM init error: %s", e)

    enabled = marketplace_registry.all_enabled()
    logger.info(
        "Marketplaces: %d enabled — %s",
        len(enabled), [m.key for m in enabled],
    )

    # Lazy-import graph to trigger compilation
    try:
        from app.graph import graph  # noqa: F401
        logger.info("LangGraph compiled ✓ (%d nodes)", len(graph.nodes))
    except Exception as e:
        logger.error("LangGraph compilation failed: %s", e)

    # Optional: init PostgreSQL
    await _init_pg()

    yield

    # Cleanup
    if _redis_client:
        await _redis_client.close()
    if _pg_pool:
        await _pg_pool.close()
    logger.info("=== Shutdown ===")


# ── App ───────────────────────────────────────────────────────────────────────


app = FastAPI(
    title="AI Price Comparison",
    description="LangGraph-powered price comparison across Indian e-commerce",
    version="3.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── JSON serializer helper ───────────────────────────────────────────────────

def _serialize(obj):
    """JSON-safe serialization for Pydantic models and other objects."""
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if hasattr(obj, "dict"):
        return obj.dict()
    return str(obj)


# ═══════════════════════════════════════════════════════════════════════════════
# SSE Streaming endpoint (master prompt spec)
# ═══════════════════════════════════════════════════════════════════════════════


@app.post("/api/compare")
async def compare_stream(request: CompareRequest):
    """POST /api/compare → SSE streaming via LangGraph astream.

    SSE events emitted:
      scraping_started → all scrapers fired
      site_done        → per site completion + SiteStatus
      matching_done    → Matcher completed + count
      ranking_done     → Ranker completed
      final_result     → complete final_response JSON
    """
    if not request.query and not request.product_url:
        raise HTTPException(status_code=400, detail="Provide query or product_url")

    query = request.query or request.product_url or ""
    mode = request.mode or (request.preferences.mode if request.preferences else "balanced")

    # Check Redis cache first
    cached = await _get_cache(query, mode)
    if cached:
        async def cached_gen():
            yield f"event: final_result\ndata: {json.dumps(cached, default=_serialize)}\n\n"
        return StreamingResponse(
            cached_gen(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
        )

    async def event_generator():
        from app.graph import graph

        initial_state = {
            "query": query,
            "mode": mode,
            "match_attempts": 0,
            "raw_results": [],
            "site_statuses": [],
        }

        start_time = time.time()
        final_state = {}
        scrapers_announced = False

        try:
            async for chunk in graph.astream(initial_state, stream_mode="updates"):
                for node_name, update in chunk.items():
                    final_state.update(update)

                    if node_name == "planner":
                        target_sites = update.get("target_sites", [])
                        yield (
                            f"event: scraping_started\n"
                            f"data: {json.dumps({'sites': target_sites})}\n\n"
                        )
                        scrapers_announced = True

                    elif node_name in [cfg.key for cfg in marketplace_registry.all_enabled()]:
                        # Per-site completion
                        statuses = update.get("site_statuses", [])
                        for s in statuses:
                            sd = s.model_dump() if hasattr(s, "model_dump") else _serialize(s)
                            yield (
                                f"event: site_done\n"
                                f"data: {json.dumps(sd, default=str)}\n\n"
                            )

                    elif node_name == "matcher":
                        matched = update.get("matched_results", [])
                        yield (
                            f"event: matching_done\n"
                            f"data: {json.dumps({'matched_count': len(matched)})}\n\n"
                        )

                    elif node_name == "ranker":
                        ranked = update.get("ranked_results", [])
                        yield (
                            f"event: ranking_done\n"
                            f"data: {json.dumps({'ranked_count': len(ranked)})}\n\n"
                        )

                    elif node_name == "explainer":
                        fr = update.get("final_response", {})
                        # Serialize Pydantic models in final_response
                        serialized = {}
                        for k, v in fr.items():
                            if isinstance(v, list):
                                serialized[k] = [
                                    o.model_dump() if hasattr(o, "model_dump") else o
                                    for o in v
                                ]
                            elif hasattr(v, "model_dump"):
                                serialized[k] = v.model_dump()
                            else:
                                serialized[k] = v

                        serialized["query_time_seconds"] = round(time.time() - start_time, 3)

                        yield (
                            f"event: final_result\n"
                            f"data: {json.dumps(serialized, default=str)}\n\n"
                        )

                        # Cache + log
                        await _set_cache(query, mode, serialized)
                        ranked_offers = fr.get("ranked_offers", [])
                        if ranked_offers:
                            await _log_prices(query, mode, ranked_offers)

        except Exception as e:
            logger.exception("SSE pipeline error: %s", e)
            yield (
                f"event: error\n"
                f"data: {json.dumps({'error': str(e)[:200]})}\n\n"
            )

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Synchronous JSON endpoint (backward-compatible)
# ═══════════════════════════════════════════════════════════════════════════════


@app.post("/api/compare/sync", response_model=CompareResponse)
async def compare_sync(request: CompareRequest):
    """POST /api/compare/sync → Full JSON response (backward-compatible)."""
    if not request.query and not request.product_url:
        raise HTTPException(status_code=400, detail="Provide query or product_url")

    query = request.query or request.product_url or ""
    mode = request.mode or (request.preferences.mode if request.preferences else "balanced")

    # Check Redis cache
    cached = await _get_cache(query, mode)
    if cached:
        return CompareResponse(
            query_time_seconds=0.0,
            final_offers=cached.get("ranked_offers", []),
            offers=cached.get("ranked_offers", []),
            site_statuses=cached.get("site_statuses", []),
            explanation=cached.get("explanation", ""),
            recommendation=cached.get("best_deal"),
        )

    start = time.time()

    try:
        from app.graph import graph

        initial_state = {
            "query": query,
            "mode": mode,
            "match_attempts": 0,
            "raw_results": [],
            "site_statuses": [],
        }

        result = await graph.ainvoke(initial_state)

    except Exception as exc:
        logger.exception("Pipeline error: %s", exc)
        raise HTTPException(status_code=500, detail=f"Pipeline error: {exc}") from exc

    final_response = result.get("final_response", {})
    ranked = final_response.get("ranked_offers", [])
    site_statuses = final_response.get("site_statuses", [])
    explanation = final_response.get("explanation", "")
    best_deal = final_response.get("best_deal")

    # Cache + log
    elapsed = round(time.time() - start, 3)
    cache_data = {
        "ranked_offers": [o.model_dump() if hasattr(o, "model_dump") else o for o in ranked],
        "site_statuses": [s.model_dump() if hasattr(s, "model_dump") else s for s in site_statuses],
        "explanation": explanation,
        "best_deal": best_deal.model_dump() if hasattr(best_deal, "model_dump") else best_deal,
        "query_time_seconds": elapsed,
    }
    await _set_cache(query, mode, cache_data)
    if ranked:
        await _log_prices(query, mode, ranked)

    return CompareResponse(
        query_time_seconds=elapsed,
        normalized_product=result.get("normalized_product"),
        selected_marketplaces=result.get("target_sites", []),
        counts={
            "raw_listings": len(result.get("raw_results", [])),
            "normalized_offers": len(result.get("cleaned_results", [])),
            "matched_offers": len(result.get("matched_results", [])),
            "ranked_offers": len(ranked),
        },
        final_offers=ranked,
        offers=ranked,
        recommendation=best_deal,
        total_offers_found=len(ranked),
        site_statuses=site_statuses,
        explanation=explanation,
        errors=[],
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Debug endpoint (backward-compatible)
# ═══════════════════════════════════════════════════════════════════════════════


@app.post("/api/debug/compare")
async def debug_compare(request: CompareRequest):
    """Extended debug endpoint — returns all intermediate data."""
    if not request.query and not request.product_url:
        raise HTTPException(status_code=400, detail="Provide query or product_url")

    query = request.query or request.product_url or ""
    mode = request.mode or "balanced"
    start = time.time()

    try:
        from app.graph import graph

        initial_state = {
            "query": query,
            "mode": mode,
            "match_attempts": 0,
            "raw_results": [],
            "site_statuses": [],
        }

        result = await graph.ainvoke(initial_state)

    except Exception as exc:
        logger.exception("Debug pipeline error: %s", exc)
        return {
            "error": str(exc),
            "query_time_seconds": round(time.time() - start, 3),
        }

    final_response = result.get("final_response", {})

    return {
        "query_time_seconds": round(time.time() - start, 3),
        "normalized_product": result.get("normalized_product"),
        "target_sites": result.get("target_sites", []),
        "match_attempts": result.get("match_attempts", 0),
        "counts": {
            "raw_results": len(result.get("raw_results", [])),
            "cleaned_results": len(result.get("cleaned_results", [])),
            "matched_results": len(result.get("matched_results", [])),
            "ranked_results": len(final_response.get("ranked_offers", [])),
        },
        "raw_results": result.get("raw_results", []),
        "cleaned_results": result.get("cleaned_results", []),
        "matched_results": result.get("matched_results", []),
        "final_response": final_response,
        "site_statuses": result.get("site_statuses", []),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Chatbot Assistant endpoint (Feature 2 — independent from Feature 1)
# ═══════════════════════════════════════════════════════════════════════════════


@app.post("/api/chat")
async def chat_endpoint(chat_req: ChatRequest):
    """POST /api/chat → Chatbot Assistant.

    3-step pipeline: Intent → SerpAPI Search → LLM Response.
    Fully independent from the price comparison pipeline.
    """
    from app.chatbot.service import run_chatbot

    # Redis cache check (10 min TTL, chatbot-specific key)
    cache_key = f"chat:{chat_req.message.lower().strip()}"
    cached = await _get_chatbot_cache(cache_key)
    if cached is not None:
        return cached

    # Run the 3-step chatbot pipeline
    result = await run_chatbot(chat_req)

    # Cache successful responses only (not error fallbacks)
    _error_phrases = {"something went wrong", "i'm having trouble"}
    if not any(phrase in result.message.lower() for phrase in _error_phrases):
        await _set_chatbot_cache(cache_key, result)

    return result


async def _get_chatbot_cache(key: str):
    """Check Redis for cached chatbot response. Returns dict or None."""
    r = await _get_redis()
    if not r:
        return None
    try:
        cached = await r.get(key)
        if cached:
            logger.info("Chatbot cache HIT: %s", key[:60])
            return json.loads(cached)
    except Exception as e:
        logger.warning("Chatbot cache get error: %s", str(e)[:60])
    return None


async def _set_chatbot_cache(key: str, result):
    """Store chatbot response in Redis with 10 min TTL."""
    r = await _get_redis()
    if not r:
        return
    try:
        data = result.model_dump() if hasattr(result, "model_dump") else result
        await r.set(key, json.dumps(data, default=str), ex=600)
        logger.info("Chatbot cache SET: %s (TTL=600s)", key[:60])
    except Exception as e:
        logger.warning("Chatbot cache set error: %s", str(e)[:60])


# ═══════════════════════════════════════════════════════════════════════════════
# Info / Health / Marketplace endpoints
# ═══════════════════════════════════════════════════════════════════════════════


@app.get("/")
async def root():
    return {
        "name": "AI Price Comparison",
        "version": "3.0.0",
        "mode": "LangGraph + Groq",
        "docs": "/docs",
        "health": "/health",
    }


@app.get("/health")
async def health():
    enabled = marketplace_registry.all_enabled()
    return {
        "status": "ok",
        "mode": "LangGraph + Groq",
        "llm_enabled": llm_client.enabled,
        "llm_model": llm_client.primary_model if llm_client.enabled else None,
        "groq_key_present": bool(settings.groq_api_key),
        "marketplaces": [m.key for m in enabled],
        "total_markets": len(enabled),
        "redis_available": _REDIS_AVAILABLE and bool(getattr(settings, "redis_url", "")),
        "pg_available": _pg_pool is not None,
    }


@app.get("/api/marketplaces")
async def list_marketplaces():
    return {
        "marketplaces": [
            {
                "key": m.key,
                "name": m.name,
                "enabled": m.enabled,
                "base_url": m.base_url,
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
            "key": m.key,
            "name": m.name,
            "search_url": m.search_url_pattern.format(query="test"),
            "status": "ready",
        }
        for m in enabled
    ]
    groq_ok = bool(settings.groq_api_key)
    return {
        "mode": "LangGraph + Groq",
        "llm_model": llm_client.primary_model if llm_client.enabled else "disabled",
        "groq_key_present": groq_ok,
        "enabled_sites": len(sites),
        "sites": sites,
        "status": "ready" if groq_ok else "ERROR: missing GROQ_API_KEY",
    }
