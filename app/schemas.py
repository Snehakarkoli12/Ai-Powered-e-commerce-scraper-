# -*- coding: utf-8 -*-
"""
Central Pydantic schemas for the entire pipeline.
All agents import from here — never define models elsewhere.

Pydantic v2 compliant — no class Config anywhere.
"""
from __future__ import annotations
from enum import Enum
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field


# ═══════════════════════════════════════════════════════════════════════════════
# ENUMS
# ═══════════════════════════════════════════════════════════════════════════════


class RankingMode(str, Enum):
    cheapest = "cheapest"
    fastest  = "fastest"
    reliable = "reliable"
    balanced = "balanced"


class SiteStatusCode(str, Enum):
    PENDING       = "pending"
    OK            = "ok"
    NO_RESULTS    = "no_results"
    BOT_CHALLENGE = "bot_challenge"
    TIMEOUT       = "timeout"
    ERROR         = "error"


# ═══════════════════════════════════════════════════════════════════════════════
# REQUEST / PREFERENCES
# ═══════════════════════════════════════════════════════════════════════════════


class RankingPreferences(BaseModel):
    mode: str = Field(
        "balanced",
        description="cheapest | fastest | reliable | balanced",
    )
    min_match_score: float = Field(0.5, ge=0.0, le=1.0)

    def mode_enum(self) -> RankingMode:
        try:
            return RankingMode(self.mode)
        except ValueError:
            return RankingMode.balanced


class CompareRequest(BaseModel):
    query:                Optional[str]       = None
    product_url:          Optional[str]       = None
    preferences:          RankingPreferences  = Field(default_factory=RankingPreferences)
    allowed_marketplaces: Optional[List[str]] = None


# ═══════════════════════════════════════════════════════════════════════════════
# PLANNER OUTPUT
# ═══════════════════════════════════════════════════════════════════════════════


class ProductAttributes(BaseModel):
    brand:           Optional[str]  = None
    model:           Optional[str]  = None
    storage:         Optional[str]  = None
    ram:             Optional[str]  = None
    color:           Optional[str]  = None
    variant:         Optional[str]  = None
    category:        Optional[str]  = None
    raw_query:       Optional[str]  = None
    image_url:       Optional[str]  = None
    extras:          Dict[str, Any] = Field(default_factory=dict)
    variant_tokens:  List[str]      = Field(default_factory=list)
    target_keywords: List[str]      = Field(default_factory=list)


class NormalizedProduct(BaseModel):
    attributes:         ProductAttributes = Field(default_factory=ProductAttributes)
    search_query:       str               = ""
    source_url:         Optional[str]     = None
    source_marketplace: Optional[str]     = None


# ═══════════════════════════════════════════════════════════════════════════════
# SCRAPER OUTPUT
# ═══════════════════════════════════════════════════════════════════════════════


class SiteStatus(BaseModel):
    marketplace_key:  str            = ""
    marketplace_name: str            = ""
    status:           SiteStatusCode = SiteStatusCode.PENDING
    message:          str            = ""
    listings_found:   int            = 0


class RawListing(BaseModel):
    platform_key:         str
    listing_url:          str            = ""
    title:                str            = ""
    price_text:           Optional[str]  = None
    original_price_text:  Optional[str]  = None
    rating_text:          Optional[str]  = None
    review_count_text:    Optional[str]  = None
    delivery_text:        Optional[str]  = None
    shipping_text:        Optional[str]  = None
    seller_text:          Optional[str]  = None
    return_policy_text:   Optional[str]  = None
    warranty_text:        Optional[str]  = None
    image_url:            Optional[str]  = None
    coupon_text:          Optional[str]  = None
    extra:                Dict[str, Any] = Field(default_factory=dict)


# ═══════════════════════════════════════════════════════════════════════════════
# SCORE BREAKDOWN
# ═══════════════════════════════════════════════════════════════════════════════


class ScoreBreakdown(BaseModel):
    price_score:    float = 0.0
    delivery_score: float = 0.0
    trust_score:    float = 0.0
    final_score:    float = 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# NORMALIZED OFFER
# ═══════════════════════════════════════════════════════════════════════════════


class NormalizedOffer(BaseModel):
    # Identity
    platform_key:   str           = ""
    platform_name:  str           = ""
    listing_url:    str           = ""
    title:          str           = ""
    image_url:      Optional[str] = None
    seller_name:    Optional[str] = None

    # Pricing
    base_price:       Optional[float] = None
    discounted_price: Optional[float] = None
    coupon_savings:   float           = 0.0
    shipping_fee:     float           = 0.0
    effective_price:  Optional[float] = None

    # Delivery
    delivery_days_min: Optional[int] = None
    delivery_days_max: Optional[int] = None
    delivery_text:     Optional[str] = None

    # Trust signals
    seller_rating:      Optional[float] = None
    review_count:       Optional[int]   = None
    return_policy_days: Optional[int]   = None
    return_type:        Optional[str]   = None
    warranty_text:      Optional[str]   = None

    # Scoring — populated by Matcher + Ranker
    match_score:         float          = 0.0
    score_breakdown:     ScoreBreakdown = Field(default_factory=ScoreBreakdown)
    recommendation_note: Optional[str]  = None
    rank:                int            = 0
    badges:              List[str]      = Field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════════════════
# PIPELINE STATE
# ═══════════════════════════════════════════════════════════════════════════════


class PipelineState(BaseModel):
    model_config = {"arbitrary_types_allowed": True, "extra": "ignore"}

    # Input
    request:     Optional[CompareRequest] = None
    preferences: RankingPreferences       = Field(default_factory=RankingPreferences)

    # Planner output
    normalized_product:        Optional[NormalizedProduct] = None
    # ↓ This is the ONE writable field — scraper.py and planner.py both write here
    selected_marketplace_keys: List[str]                   = Field(default_factory=list)

    # Scraper output
    raw_listings:  List[RawListing]  = Field(default_factory=list)
    site_statuses: List[SiteStatus]  = Field(default_factory=list)

    # Extractor output
    normalized_offers: List[NormalizedOffer] = Field(default_factory=list)

    # Matcher output
    matched_offers: List[NormalizedOffer] = Field(default_factory=list)

    # Ranker output
    final_offers:  List[NormalizedOffer] = Field(default_factory=list)
    ranked_offers: List[NormalizedOffer] = Field(default_factory=list)

    # Pipeline-wide
    errors:      List[str] = Field(default_factory=list)
    explanation: str       = ""

    # ── Helpers ───────────────────────────────────────────────────────────────

    def add_error(self, msg: str) -> None:
        self.errors.append(msg)

    def get_site_statuses_list(self) -> List[SiteStatus]:
        return self.site_statuses

    def get_selected_marketplaces(self) -> List[str]:
        """Use this instead of a @property — Pydantic v2 blocks property reads."""
        return self.selected_marketplace_keys

    def set_site_status(
        self,
        status_or_key: Union[SiteStatus, str],
        marketplace_name: str       = "",
        status:           SiteStatusCode = SiteStatusCode.ERROR,
        message:          str       = "",
        listings_found:   int       = 0,
    ) -> None:
        """
        Accepts EITHER a SiteStatus object OR individual keyword args.

        Style 1 — scraper.py uses this:
            state.set_site_status(site_status_obj)

        Style 2 — explicit kwargs:
            state.set_site_status("amazon", "Amazon India", SiteStatusCode.OK, "done", 5)
        """
        # ── Style 1: full SiteStatus object passed ────────────────────────────
        if isinstance(status_or_key, SiteStatus):
            obj = status_or_key
            for existing in self.site_statuses:
                if existing.marketplace_key == obj.marketplace_key:
                    existing.status         = obj.status
                    existing.message        = obj.message
                    existing.listings_found = obj.listings_found
                    return
            self.site_statuses.append(obj)
            return

        # ── Style 2: individual fields passed ────────────────────────────────
        marketplace_key = str(status_or_key)
        for existing in self.site_statuses:
            if existing.marketplace_key == marketplace_key:
                existing.status         = status
                existing.message        = message
                existing.listings_found = listings_found
                return
        self.site_statuses.append(SiteStatus(
            marketplace_key=marketplace_key,
            marketplace_name=marketplace_name,
            status=status,
            message=message,
            listings_found=listings_found,
        ))


# ═══════════════════════════════════════════════════════════════════════════════
# API RESPONSE
# ═══════════════════════════════════════════════════════════════════════════════


class CountsSummary(BaseModel):
    raw_listings:      int = 0
    normalized_offers: int = 0
    matched_offers:    int = 0
    ranked_offers:     int = 0


class CompareResponse(BaseModel):
    query_time_seconds:    float                       = 0.0
    normalized_product:    Optional[NormalizedProduct] = None
    selected_marketplaces: List[str]                   = Field(default_factory=list)
    counts:                CountsSummary               = Field(default_factory=CountsSummary)
    final_offers:          List[NormalizedOffer]       = Field(default_factory=list)
    offers:                List[NormalizedOffer]       = Field(default_factory=list)
    recommendation:        Optional[NormalizedOffer]   = None
    total_offers_found:    int                         = 0
    site_statuses:         List[SiteStatus]            = Field(default_factory=list)
    explanation:           Optional[str]               = None
    errors:                List[str]                   = Field(default_factory=list)


class DebugCompareResponse(CompareResponse):
    """Extended response for /api/debug/compare."""
    raw_listings:            List[RawListing]     = Field(default_factory=list)
    normalized_before_match: List[NormalizedOffer] = Field(default_factory=list)
