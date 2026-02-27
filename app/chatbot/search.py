# -*- coding: utf-8 -*-
"""
Step 2 — SerpAPI Google Shopping search for Chatbot Assistant (Feature 2).

Fetches up to 10 product results from Google Shopping (India).
Returns empty list on failure — never raises exceptions.
"""
from __future__ import annotations

import asyncio
from typing import List

from app.chatbot.schemas import ShoppingResult
from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def fetch_shopping_results(message: str, intent: str) -> List[ShoppingResult]:
    """Fetch Google Shopping results via SerpAPI.

    - If intent == "general": returns empty list immediately (no API call).
    - Otherwise: calls SerpAPI with gl="in", hl="en", num=10.
    - On ANY failure: logs error, returns empty list.
    """
    if intent == "general":
        logger.info("Intent is 'general' — skipping SerpAPI call")
        return []

    try:
        from serpapi import GoogleSearch

        api_key = settings.serpapi_key.strip()
        if not api_key:
            logger.error("SERPAPI_KEY not set in .env — cannot fetch shopping results")
            return []

        params = {
            "engine": "google_shopping",
            "q": message,
            "api_key": api_key,
            "gl": "in",
            "hl": "en",
            "num": 10,
        }

        # Run blocking SerpAPI call in thread pool to keep async
        loop = asyncio.get_event_loop()
        search = GoogleSearch(params)
        results = await loop.run_in_executor(None, search.get_dict)

        shopping_results = results.get("shopping_results", [])

        if not shopping_results:
            logger.info("SerpAPI returned 0 shopping results for: '%s'", message[:60])
            return []

        products: List[ShoppingResult] = []
        for item in shopping_results[:10]:
            products.append(
                ShoppingResult(
                    title=item.get("title", ""),
                    price=item.get("price", None),
                    rating=item.get("rating", None),
                    reviews=item.get("reviews", None),
                    source=item.get("source", None),
                    delivery=item.get("delivery", None),
                    thumbnail=item.get("thumbnail", None),
                    link=item.get("link", None),
                )
            )

        logger.info(
            "SerpAPI: %d products found for '%s'",
            len(products), message[:60],
        )
        return products

    except Exception as e:
        logger.error("SerpAPI fetch failed: %s", str(e)[:150])
        return []
