# -*- coding: utf-8 -*-
"""
LangGraph StateGraph — full pipeline wiring.

Framework: LangGraph (NOT CrewAI, NOT AutoGen — Constraint #1)

NODES:
  planner     — Groq Llama 3.3 70B query parsing
  <site_key>  — One node per enabled marketplace (parallel)
  extractor   — Pure Python normalization
  matcher     — Pure Python scoring + gates
  ranker      — Pure Python ranking + badges
  explainer   — Groq Llama 3.3 70B recommendation

EDGES:
  START → planner
  planner → [all scraper nodes] (parallel fan-out)
  [all scraper nodes] → extractor (fan-in, waits for ALL)
  extractor → matcher
  matcher → conditional:
    matched + not empty → ranker
    matched empty + attempts < 2 → planner (retry loop)
    matched empty + attempts >= 2 → explainer (graceful fail)
  ranker → explainer
  explainer → END

Constraint #6: raw_results uses add_or_reset (operator.add equivalent)
Constraint #7: Extractor runs ONLY after ALL scrapers complete
"""
from __future__ import annotations

from langgraph.graph import StateGraph, START, END

from app.state import CompareState
from app.agents.planner import planner_node
from app.agents.scraper import make_scraper_node
from app.agents.extractor import extractor_node
from app.agents.matcher import matcher_node, should_retry_or_continue
from app.agents.ranker import ranker_node
from app.agents.llm_ranker import explainer_node
from app.marketplaces.registry import marketplace_registry
from app.utils.logger import get_logger

logger = get_logger(__name__)


def build_graph():
    """Build and compile the LangGraph price-comparison pipeline.

    Dynamically adds one scraper node per enabled marketplace.
    All scraper nodes run in parallel (LangGraph fan-out from planner).
    Extractor waits for ALL scrapers (LangGraph fan-in).
    """
    builder = StateGraph(CompareState)

    # ── Processing nodes ─────────────────────────────────────────────────
    builder.add_node("planner",   planner_node)
    builder.add_node("extractor", extractor_node)
    builder.add_node("matcher",   matcher_node)
    builder.add_node("ranker",    ranker_node)
    builder.add_node("explainer", explainer_node)

    # ── Scraper nodes — one per enabled marketplace ──────────────────────
    site_keys = [cfg.key for cfg in marketplace_registry.all_enabled()]
    logger.info(
        "Graph: building with %d scraper nodes: %s",
        len(site_keys), site_keys,
    )

    for site_key in site_keys:
        builder.add_node(site_key, make_scraper_node(site_key))

    # ── Edges ────────────────────────────────────────────────────────────
    # START → planner
    builder.add_edge(START, "planner")

    if site_keys:
        # planner → [all scrapers] (parallel fan-out)
        for site_key in site_keys:
            builder.add_edge("planner", site_key)

        # [all scrapers] → extractor (fan-in: waits for ALL)
        for site_key in site_keys:
            builder.add_edge(site_key, "extractor")
    else:
        # No sites enabled — direct path (fallback)
        builder.add_edge("planner", "extractor")

    # extractor → matcher
    builder.add_edge("extractor", "matcher")

    # matcher → conditional edge
    builder.add_conditional_edges(
        "matcher",
        should_retry_or_continue,
        {
            "planner":   "planner",
            "ranker":    "ranker",
            "explainer": "explainer",
        },
    )

    # ranker → explainer
    builder.add_edge("ranker", "explainer")

    # explainer → END
    builder.add_edge("explainer", END)

    compiled = builder.compile()
    logger.info("Graph: compiled successfully (%d scraper nodes)", len(site_keys))
    return compiled


# ── Singleton compiled graph ─────────────────────────────────────────────────
# Built once at import time. Restart server to pick up marketplace config changes.

graph = build_graph()
