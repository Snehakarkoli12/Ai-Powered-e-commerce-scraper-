# -*- coding: utf-8 -*-
"""
Pydantic V2 schemas for the Watchlist feature.

Follows same style as app/schemas.py.
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, EmailStr, Field


# ═══════════════════════════════════════════════════════════════════════════════
# REQUESTS
# ═══════════════════════════════════════════════════════════════════════════════


class SaveItemRequest(BaseModel):
    user_email:      EmailStr
    product_query:   str   = Field(..., min_length=1, max_length=500)
    product_title:   str   = Field(..., min_length=1, max_length=500)
    site:            str
    saved_price:     float = Field(..., gt=0)
    product_url:     str
    thumbnail_url:   Optional[str] = None
    mode:            str   = "balanced"
    alert_threshold: float = Field(5.0, ge=1.0, le=50.0)


class RemoveItemRequest(BaseModel):
    item_id:    str
    user_email: EmailStr


# ═══════════════════════════════════════════════════════════════════════════════
# RESPONSES
# ═══════════════════════════════════════════════════════════════════════════════


class WatchlistItemResponse(BaseModel):
    id:               str
    user_email:       str
    product_title:    str
    site:             str
    saved_price:      float
    current_price:    Optional[float] = None
    price_change_pct: Optional[float] = None
    price_dropped:    bool = False
    product_url:      str
    thumbnail_url:    Optional[str] = None
    mode:             str
    alert_threshold:  float
    saved_at:         datetime
    last_checked:     Optional[datetime] = None
    last_notified:    Optional[datetime] = None
    is_active:        bool = True
    product_query:    Optional[str] = None


class PriceHistoryPoint(BaseModel):
    price:      float
    checked_at: datetime
    in_stock:   bool


class WatchlistWithHistory(BaseModel):
    item:    WatchlistItemResponse
    history: List[PriceHistoryPoint]


class WatchlistListResponse(BaseModel):
    items: List[WatchlistItemResponse]
    total: int
