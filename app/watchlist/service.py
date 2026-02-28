# -*- coding: utf-8 -*-
"""
Watchlist service — CRUD operations for watchlist items and price history.

All functions are async. Uses SQLAlchemy AsyncSession.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select, func, delete, update

from app.config import settings
from app.utils.logger import get_logger
from app.watchlist.models import WatchlistItem, PriceHistory, async_session
from app.watchlist.schemas import (
    SaveItemRequest,
    RemoveItemRequest,
    WatchlistItemResponse,
    WatchlistListResponse,
    WatchlistWithHistory,
    PriceHistoryPoint,
)

logger = get_logger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════════════


def _row_to_response(row: WatchlistItem) -> WatchlistItemResponse:
    """Convert a SQLAlchemy WatchlistItem row to a WatchlistItemResponse."""
    price_change_pct = None
    price_dropped = False

    if row.current_price is not None and row.saved_price:
        price_change_pct = round(
            ((row.saved_price - row.current_price) / row.saved_price) * 100, 2
        )
        price_dropped = row.current_price < row.saved_price

    return WatchlistItemResponse(
        id=row.id,
        user_email=row.user_email,
        product_title=row.product_title,
        site=row.site,
        saved_price=row.saved_price,
        current_price=row.current_price,
        price_change_pct=price_change_pct,
        price_dropped=price_dropped,
        product_url=row.product_url,
        thumbnail_url=row.thumbnail_url,
        mode=row.mode or "balanced",
        alert_threshold=row.alert_threshold or 5.0,
        saved_at=row.saved_at or datetime.utcnow(),
        last_checked=row.last_checked,
        last_notified=row.last_notified,
        is_active=row.is_active,
        product_query=row.product_query,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# SAVE ITEM
# ═══════════════════════════════════════════════════════════════════════════════


async def save_item(db, req: SaveItemRequest) -> WatchlistItemResponse:
    """Save a product to the user's watchlist.

    Step 1: Check duplicate (same user + product_url + active).
    Step 2: Check count limit (max items per user).
    Step 3: Insert new row.
    Step 4: Insert first price_history row.
    Step 5: Commit + return response.
    """
    # Step 1: Check duplicate
    stmt = select(WatchlistItem).where(
        WatchlistItem.user_email == req.user_email,
        WatchlistItem.product_url == req.product_url,
        WatchlistItem.is_active == True,
    )
    result = await db.execute(stmt)
    existing = result.scalars().first()
    if existing:
        logger.info("Duplicate watchlist item for %s — returning existing", req.user_email)
        return _row_to_response(existing)

    # Step 2: Check count limit
    count_stmt = select(func.count()).select_from(WatchlistItem).where(
        WatchlistItem.user_email == req.user_email,
        WatchlistItem.is_active == True,
    )
    count_result = await db.execute(count_stmt)
    count = count_result.scalar() or 0
    if count >= settings.watchlist_max_items_per_user:
        raise HTTPException(
            status_code=400,
            detail=f"Watchlist full. Max {settings.watchlist_max_items_per_user} items.",
        )

    # Step 3: Insert new item
    item_id = str(uuid4())
    now = datetime.utcnow()
    new_item = WatchlistItem(
        id=item_id,
        user_email=req.user_email,
        product_query=req.product_query,
        product_title=req.product_title,
        site=req.site,
        saved_price=req.saved_price,
        current_price=None,
        product_url=req.product_url,
        thumbnail_url=req.thumbnail_url,
        mode=req.mode,
        alert_threshold=req.alert_threshold,
        is_active=True,
        saved_at=now,
        last_checked=None,
        last_notified=None,
    )
    db.add(new_item)

    # Step 4: Insert first price_history row
    history_entry = PriceHistory(
        id=str(uuid4()),
        watchlist_id=item_id,
        price=req.saved_price,
        checked_at=now,
        in_stock=True,
    )
    db.add(history_entry)

    # Step 5: Commit
    await db.commit()
    await db.refresh(new_item)

    logger.info(
        "Saved watchlist item: %s for %s (₹%.0f on %s)",
        req.product_title[:40], req.user_email, req.saved_price, req.site,
    )
    return _row_to_response(new_item)


# ═══════════════════════════════════════════════════════════════════════════════
# GET USER WATCHLIST
# ═══════════════════════════════════════════════════════════════════════════════


async def get_user_watchlist(db, user_email: str) -> WatchlistListResponse:
    """Get all active watchlist items for a user, ordered by saved_at DESC."""
    stmt = (
        select(WatchlistItem)
        .where(
            WatchlistItem.user_email == user_email,
            WatchlistItem.is_active == True,
        )
        .order_by(WatchlistItem.saved_at.desc())
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()

    items = [_row_to_response(row) for row in rows]
    return WatchlistListResponse(items=items, total=len(items))


# ═══════════════════════════════════════════════════════════════════════════════
# GET ALL ACTIVE ITEMS (for scheduler)
# ═══════════════════════════════════════════════════════════════════════════════


async def get_all_active_items(db) -> list[WatchlistItemResponse]:
    """Get ALL active watchlist items across all users. Used by scheduler only."""
    stmt = select(WatchlistItem).where(WatchlistItem.is_active == True)
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return [_row_to_response(row) for row in rows]


# ═══════════════════════════════════════════════════════════════════════════════
# REMOVE ITEM (soft delete)
# ═══════════════════════════════════════════════════════════════════════════════


async def remove_item(db, req: RemoveItemRequest) -> dict:
    """Soft-delete a watchlist item (set is_active=False)."""
    stmt = select(WatchlistItem).where(
        WatchlistItem.id == req.item_id,
        WatchlistItem.user_email == req.user_email,
    )
    result = await db.execute(stmt)
    item = result.scalars().first()

    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    item.is_active = False
    await db.commit()

    logger.info("Removed watchlist item %s for %s", req.item_id, req.user_email)
    return {"message": "removed", "item_id": req.item_id}


# ═══════════════════════════════════════════════════════════════════════════════
# GET ITEM WITH HISTORY
# ═══════════════════════════════════════════════════════════════════════════════


async def get_item_with_history(db, item_id: str, user_email: str) -> WatchlistWithHistory:
    """Get a single watchlist item + its full price history."""
    # Get item
    stmt = select(WatchlistItem).where(
        WatchlistItem.id == item_id,
        WatchlistItem.user_email == user_email,
    )
    result = await db.execute(stmt)
    item = result.scalars().first()

    if not item:
        raise HTTPException(status_code=404, detail="Not found")

    # Get price history
    history_stmt = (
        select(PriceHistory)
        .where(PriceHistory.watchlist_id == item_id)
        .order_by(PriceHistory.checked_at.asc())
    )
    history_result = await db.execute(history_stmt)
    history_rows = history_result.scalars().all()

    history = [
        PriceHistoryPoint(
            price=h.price,
            checked_at=h.checked_at,
            in_stock=h.in_stock,
        )
        for h in history_rows
    ]

    return WatchlistWithHistory(item=_row_to_response(item), history=history)


# ═══════════════════════════════════════════════════════════════════════════════
# UPDATE PRICE
# ═══════════════════════════════════════════════════════════════════════════════


async def update_price(db, item_id: str, new_price: float, in_stock: bool = True) -> None:
    """Update current_price + last_checked on a watchlist item, insert price_history row."""
    now = datetime.utcnow()

    # Update the watchlist item
    stmt = (
        update(WatchlistItem)
        .where(WatchlistItem.id == item_id)
        .values(current_price=new_price, last_checked=now)
    )
    await db.execute(stmt)

    # Insert price history
    history_entry = PriceHistory(
        id=str(uuid4()),
        watchlist_id=item_id,
        price=new_price,
        checked_at=now,
        in_stock=in_stock,
    )
    db.add(history_entry)
    await db.commit()


# ═══════════════════════════════════════════════════════════════════════════════
# UPDATE LAST NOTIFIED
# ═══════════════════════════════════════════════════════════════════════════════


async def update_last_notified(db, item_id: str) -> None:
    """Set last_notified = now for a watchlist item."""
    stmt = (
        update(WatchlistItem)
        .where(WatchlistItem.id == item_id)
        .values(last_notified=datetime.utcnow())
    )
    await db.execute(stmt)
    await db.commit()


# ═══════════════════════════════════════════════════════════════════════════════
# CLEANUP OLD HISTORY
# ═══════════════════════════════════════════════════════════════════════════════


async def cleanup_old_history(db) -> int:
    """Delete price_history rows older than PRICE_HISTORY_RETENTION_DAYS."""
    cutoff = datetime.utcnow() - timedelta(days=settings.price_history_retention_days)
    stmt = delete(PriceHistory).where(PriceHistory.checked_at < cutoff)
    result = await db.execute(stmt)
    count = result.rowcount
    await db.commit()
    logger.info("Cleaned %d old price history rows (older than %s)", count, cutoff.date())
    return count
