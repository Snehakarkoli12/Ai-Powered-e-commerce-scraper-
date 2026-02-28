# -*- coding: utf-8 -*-
"""
Price monitor — re-runs the existing LangGraph pipeline for watchlist items.

Imports and invokes the existing compiled graph.
Does NOT modify any existing agent or pipeline code.
"""
from __future__ import annotations

import asyncio
from datetime import datetime

from app.graph import graph as comparison_graph
from app.utils.logger import get_logger
from app.watchlist.schemas import WatchlistItemResponse
from app.watchlist.service import (
    get_all_active_items,
    update_price,
    update_last_notified,
    cleanup_old_history,
)
from app.watchlist.email_sender import send_price_drop_email

logger = get_logger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# CHECK PRICE FOR SINGLE ITEM
# ═══════════════════════════════════════════════════════════════════════════════


async def check_price_for_item(db, item: WatchlistItemResponse) -> None:
    """Re-run the full LangGraph pipeline for one watchlist item.

    Steps:
      1. Build initial CompareState
      2. Invoke existing compiled graph
      3. Extract new price from ranked_results matching item.site
      4. Update DB
      5. Check alert condition → send email if threshold met
      6. Handle errors gracefully (never raise)
    """
    try:
        # Step 1: Build initial state matching CompareState TypedDict
        # Use product_query (the original search query) for better pipeline results
        search_query = item.product_query or item.product_title
        initial_state = {
            "query":           search_query,
            "mode":            item.mode or "balanced",
            "raw_results":     [],
            "site_statuses":   [],
            "cleaned_results": [],
            "matched_results": [],
            "ranked_results":  [],
            "match_attempts":  0,
        }

        # Step 2: Invoke the existing compiled LangGraph pipeline
        logger.info(
            "Price check: running pipeline for '%s' on %s",
            item.product_title[:40], item.site,
        )
        result = await comparison_graph.ainvoke(initial_state)

        # Step 3: Extract new price for the specific site
        ranked = result.get("ranked_results", [])
        new_price = None
        in_stock = False

        for offer in ranked:
            offer_site = getattr(offer, "site", "") or getattr(offer, "platform_key", "")
            if offer_site.lower() == item.site.lower():
                new_price = getattr(offer, "effective_price", None)
                if new_price is not None:
                    in_stock = True
                    break

        # Step 4: Handle not found
        if new_price is None:
            fallback_price = item.current_price if item.current_price else item.saved_price
            await update_price(db, item.id, fallback_price, in_stock=False)
            logger.info(
                "Price check: %s not found on %s (used fallback ₹%.0f)",
                item.product_title[:40], item.site, fallback_price,
            )
            return

        # Step 5: Update DB with new price
        await update_price(db, item.id, new_price, in_stock=True)

        # Step 6: Check alert condition
        #   A: new_price < saved_price
        #   B: drop_pct >= alert_threshold
        #   C: last_notified is None OR >24 hours ago
        if new_price < item.saved_price:
            drop_pct = ((item.saved_price - new_price) / item.saved_price) * 100

            if drop_pct >= item.alert_threshold:
                # 24-hour notification cooldown check
                should_notify = True
                if item.last_notified is not None:
                    hours_since = (
                        datetime.utcnow() - item.last_notified
                    ).total_seconds()
                    if hours_since < 86400:  # 24 hours in seconds
                        should_notify = False
                        logger.info(
                            "Skipping alert for %s — notified %.1fh ago",
                            item.product_title[:40],
                            hours_since / 3600,
                        )

                if should_notify:
                    loop = asyncio.get_event_loop()
                    await loop.run_in_executor(
                        None,
                        send_price_drop_email,
                        item.user_email,
                        item,
                        item.saved_price,
                        new_price,
                        drop_pct,
                    )
                    await update_last_notified(db, item.id)
                    logger.info(
                        "Alert sent: %s dropped %.1f%% to ₹%.0f",
                        item.product_title[:40], drop_pct, new_price,
                    )
        else:
            logger.info(
                "Price check: %s on %s — ₹%.0f (no drop from ₹%.0f)",
                item.product_title[:40], item.site, new_price, item.saved_price,
            )

    except Exception as e:
        logger.error(
            "Price check failed for %s: %s",
            item.product_title[:40] if item else "unknown", e,
            exc_info=True,
        )
        # Never raise — scheduler must continue to next item


# ═══════════════════════════════════════════════════════════════════════════════
# RUN ALL CHECKS (called by scheduler every N hours)
# ═══════════════════════════════════════════════════════════════════════════════


async def run_all_checks(db) -> None:
    """Check prices for ALL active watchlist items.

    Sequential with 30-second delay between items.
    MANDATORY: prevents Groq rate limit hammering.
    """
    items = await get_all_active_items(db)
    logger.info("Starting watchlist check: %d items", len(items))

    for i, item in enumerate(items):
        await check_price_for_item(db, item)
        # 30 seconds between each item — MANDATORY for Groq rate limits
        if i < len(items) - 1:
            await asyncio.sleep(30)

    # Cleanup old history entries
    await cleanup_old_history(db)

    logger.info("Watchlist check complete: %d items processed", len(items))
