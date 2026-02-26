from __future__ import annotations
from enum import Enum
from typing import Optional, List, Dict
from pydantic import BaseModel, Field


class PreferenceMode(str, Enum):
    CHEAPEST = "cheapest"
    FASTEST  = "fastest"
    RELIABLE = "reliable"
    BALANCED = "balanced"


class Preferences(BaseModel):
    mode:            PreferenceMode = PreferenceMode.BALANCED
    min_match_score: float          = Field(default=0.3, ge=0.0, le=1.0)


class CompareRequest(BaseModel):
    query:                  Optional[str]        = None
    product_url:            Optional[str]        = None
    preferences:            Preferences          = Field(default_factory=Preferences)
    allowed_marketplaces:   Optional[List[str]]  = None


class ProductAttributes(BaseModel):
    brand:     Optional[str] = None
    model:     Optional[str] = None
    storage:   Optional[str] = None
    ram:       Optional[str] = None
    color:     Optional[str] = None
    variant:   Optional[str] = None
    category:  Optional[str] = None
    raw_query: Optional[str] = None


class NormalizedProduct(BaseModel):
    attributes:         ProductAttributes
    search_query:       str
    source_url:         Optional[str] = None
    source_marketplace: Optional[str] = None


class ScoreBreakdown(BaseModel):
    price_score:    float = 0.0
    delivery_score: float = 0.0
    trust_score:    float = 0.0
    match_score:    float = 0.0
    final_score:    float = 0.0
    weights_used:   Dict[str, float] = Field(default_factory=dict)
    notes:          List[str]        = Field(default_factory=list)


class NormalizedOffer(BaseModel):
    platform_key:        str
    platform_name:       str
    listing_url:         str
    title:               str
    seller_name:         Optional[str]          = None
    base_price:          Optional[float]        = None
    discounted_price:    Optional[float]        = None
    coupon_savings:      float                  = 0.0
    shipping_fee:        float                  = 0.0
    effective_price:     Optional[float]        = None
    delivery_days_min:   Optional[int]          = None
    delivery_days_max:   Optional[int]          = None
    delivery_text:       Optional[str]          = None
    seller_rating:       Optional[float]        = None
    review_count:        Optional[int]          = None
    return_policy_days:  Optional[int]          = None
    return_type:         Optional[str]          = None
    warranty_text:       Optional[str]          = None
    match_score:         float                  = 0.0
    score_breakdown:     ScoreBreakdown         = Field(default_factory=ScoreBreakdown)
    recommendation_note: Optional[str]          = None


class RawListing(BaseModel):
    platform_key:        str
    listing_url:         str
    title:               Optional[str]  = None
    price_text:          Optional[str]  = None
    original_price_text: Optional[str]  = None
    rating_text:         Optional[str]  = None
    review_count_text:   Optional[str]  = None
    delivery_text:       Optional[str]  = None
    shipping_text:       Optional[str]  = None
    seller_text:         Optional[str]  = None
    return_policy_text:  Optional[str]  = None
    warranty_text:       Optional[str]  = None


class SiteStatusCode(str, Enum):
    PENDING        = "pending"
    OK             = "ok"
    TIMEOUT        = "timeout"
    SELECTOR_ERROR = "selector_error"
    BOT_CHALLENGE  = "bot_challenge"
    NO_RESULTS     = "no_results"
    ERROR          = "error"


class SiteStatus(BaseModel):
    marketplace_key:  str
    marketplace_name: str
    status:           SiteStatusCode = SiteStatusCode.PENDING
    message:          str            = ""
    listings_found:   int            = 0


class CompareResponse(BaseModel):
    normalized_product:  Optional[NormalizedProduct]  = None
    offers:              List[NormalizedOffer]         = Field(default_factory=list)
    recommendation:      Optional[NormalizedOffer]     = None
    explanation:         str                           = ""
    site_statuses:       List[SiteStatus]              = Field(default_factory=list)
    errors:              List[str]                     = Field(default_factory=list)
    total_offers_found:  int                           = 0
    query_time_seconds:  float                         = 0.0
