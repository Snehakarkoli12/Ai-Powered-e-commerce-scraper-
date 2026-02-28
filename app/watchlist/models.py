# -*- coding: utf-8 -*-
"""
SQLAlchemy ORM models for the Watchlist feature.

Uses async SQLAlchemy engine with asyncpg driver.
Tables: watchlist_items, price_history.
"""
from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    Boolean, Column, DateTime, Float, ForeignKey,
    String, Text, UniqueConstraint, Index,
)
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import declarative_base, sessionmaker

import os

from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)

# ── Engine & Session ──────────────────────────────────────────────────────────

_db_url = settings.database_url or ""

# Convert postgresql:// to postgresql+asyncpg:// for async driver
if _db_url.startswith("postgresql://"):
    _db_url = _db_url.replace("postgresql://", "postgresql+asyncpg://", 1)
elif _db_url.startswith("postgres://"):
    _db_url = _db_url.replace("postgres://", "postgresql+asyncpg://", 1)

# Fallback to local SQLite when no DATABASE_URL is set
if not _db_url:
    _data_dir = os.path.join(os.path.dirname(__file__), "..", "..", "data")
    os.makedirs(_data_dir, exist_ok=True)
    _sqlite_path = os.path.abspath(os.path.join(_data_dir, "watchlist.db"))
    _db_url = f"sqlite+aiosqlite:///{_sqlite_path}"
    logger.info("Watchlist using SQLite fallback: %s", _sqlite_path)

engine = create_async_engine(_db_url, echo=False)

async_session = sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)

Base = declarative_base()


# ═══════════════════════════════════════════════════════════════════════════════
# TABLE: watchlist_items
# ═══════════════════════════════════════════════════════════════════════════════


class WatchlistItem(Base):
    __tablename__ = "watchlist_items"

    id              = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_email      = Column(String(255), nullable=False, index=True)
    product_query   = Column(String(500), nullable=False)
    product_title   = Column(String(500), nullable=False)
    site            = Column(String(100), nullable=False)
    saved_price     = Column(Float, nullable=False)
    current_price   = Column(Float, nullable=True)
    product_url     = Column(Text, nullable=False)
    thumbnail_url   = Column(Text, nullable=True)
    mode            = Column(String(50), default="balanced")
    alert_threshold = Column(Float, default=5.0)
    is_active       = Column(Boolean, default=True)
    saved_at        = Column(DateTime, default=datetime.utcnow)
    last_checked    = Column(DateTime, nullable=True)
    last_notified   = Column(DateTime, nullable=True)

    __table_args__ = (
        UniqueConstraint("user_email", "product_url", name="uq_user_product"),
    )


# ═══════════════════════════════════════════════════════════════════════════════
# TABLE: price_history
# ═══════════════════════════════════════════════════════════════════════════════


class PriceHistory(Base):
    __tablename__ = "price_history_watchlist"

    id           = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    watchlist_id = Column(
        String(36),
        ForeignKey("watchlist_items.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    price       = Column(Float, nullable=False)
    checked_at  = Column(DateTime, default=datetime.utcnow, index=True)
    in_stock    = Column(Boolean, default=True)


# ═══════════════════════════════════════════════════════════════════════════════
# INIT & SESSION HELPERS
# ═══════════════════════════════════════════════════════════════════════════════


async def init_db():
    """Create tables if they don't exist. Safe to call on every startup."""
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Watchlist DB tables created / verified ✓")
    except Exception as e:
        logger.error("Watchlist DB init failed: %s", e)


async def get_db():
    """FastAPI Depends() — yields an AsyncSession, closes in finally."""
    session = async_session()
    try:
        yield session
    finally:
        await session.close()
