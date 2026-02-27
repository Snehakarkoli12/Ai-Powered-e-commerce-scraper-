# -*- coding: utf-8 -*-
"""
CompareState — LangGraph shared state for the price-comparison pipeline.

Uses TypedDict with annotated reducers for parallel scraper merge.
Constraint #6: raw_results and site_statuses use operator.add for
parallel merge, with a custom reducer that supports reset on retry.
"""
from __future__ import annotations

from typing import Annotated, Any, Dict, List, Optional, TypedDict

from app.schemas import NormalizedProduct, RawListing, NormalizedOffer, SiteStatus


# ── Custom reducer ────────────────────────────────────────────────────────────

def add_or_reset(existing: list, new) -> list:
    """Custom list reducer for LangGraph.

    - list input → concatenate to existing (parallel scraper merge).
    - None input → reset to empty list (planner retry cleanup).

    This satisfies the master prompt constraint:
      'Planner MUST reset raw_results = [] and cleaned_results = [] on retry'
    while still supporting operator.add-style parallel merge.
    """
    if new is None:
        return []
    return (existing or []) + (new or [])


# ── CompareState TypedDict ────────────────────────────────────────────────────

class CompareState(TypedDict, total=False):
    """Shared state passed between all LangGraph nodes.

    Fields are marked total=False so nodes can return partial state updates.
    LangGraph merges partial updates into the full state automatically.
    """

    # ── INPUT FIELDS (from CompareRequest, set before graph starts) ──────
    query: str
    mode: str       # "cheapest" / "balanced" / "fastest" / "reliable"

    # ── PLANNER OUTPUT ───────────────────────────────────────────────────
    brand: str
    model: str
    storage: str
    target_sites: List[str]
    normalized_product: NormalizedProduct
    match_attempts: int                      # starts at 0, NEVER reset by Planner

    # ── SCRAPER OUTPUT (parallel merge via add_or_reset) ─────────────────
    raw_results:   Annotated[list, add_or_reset]
    site_statuses: Annotated[list, add_or_reset]

    # ── EXTRACTOR OUTPUT ─────────────────────────────────────────────────
    cleaned_results: List[NormalizedOffer]

    # ── MATCHER OUTPUT ───────────────────────────────────────────────────
    matched_results: List[NormalizedOffer]

    # ── RANKER OUTPUT ────────────────────────────────────────────────────
    ranked_results: List[NormalizedOffer]

    # ── EXPLAINER OUTPUT ─────────────────────────────────────────────────
    final_response: dict
