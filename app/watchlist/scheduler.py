# -*- coding: utf-8 -*-
"""
APScheduler setup for the Watchlist price monitor.

Jobs:
  1. Price check — every N hours (default 6)
  2. History cleanup — daily at 2:00 AM IST

Uses AsyncIOScheduler to work inside FastAPI's event loop.
"""
from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import settings
from app.utils.logger import get_logger
from app.watchlist.models import async_session
from app.watchlist.price_monitor import run_all_checks
from app.watchlist.service import cleanup_old_history

logger = get_logger(__name__)

# ── Scheduler instance ────────────────────────────────────────────────────────

scheduler = AsyncIOScheduler(timezone="Asia/Kolkata")


# ── Job functions ─────────────────────────────────────────────────────────────


async def _watchlist_check_job():
    """Run price checks for all active watchlist items."""
    try:
        async with async_session() as db:
            await run_all_checks(db)
    except Exception as e:
        logger.error("Scheduler watchlist check job failed: %s", e, exc_info=True)


async def _cleanup_job():
    """Clean up old price history entries."""
    try:
        async with async_session() as db:
            await cleanup_old_history(db)
    except Exception as e:
        logger.error("Scheduler cleanup job failed: %s", e, exc_info=True)


# ── Public API ────────────────────────────────────────────────────────────────


def start_scheduler():
    """Start the APScheduler with watchlist jobs. Call from lifespan startup."""
    # Job 1: Price check every N hours
    scheduler.add_job(
        func=_watchlist_check_job,
        trigger="interval",
        hours=settings.watchlist_check_interval_hours,
        id="watchlist_price_check",
        replace_existing=True,
        misfire_grace_time=3600,
        max_instances=1,  # MANDATORY: prevents overlap
    )

    # Job 2: History cleanup daily at 2:00 AM IST
    scheduler.add_job(
        func=_cleanup_job,
        trigger="cron",
        hour=2,
        minute=0,
        id="price_history_cleanup",
        replace_existing=True,
        timezone="Asia/Kolkata",
    )

    scheduler.start()
    logger.info(
        "Watchlist scheduler started — price check every %dh, cleanup at 2AM IST",
        settings.watchlist_check_interval_hours,
    )


def stop_scheduler():
    """Shut down the scheduler. Call from lifespan shutdown."""
    try:
        scheduler.shutdown(wait=False)
        logger.info("Watchlist scheduler stopped")
    except Exception as e:
        logger.warning("Scheduler shutdown error: %s", e)
