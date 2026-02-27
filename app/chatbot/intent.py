# -*- coding: utf-8 -*-
"""
Step 1 — Intent Classifier for Chatbot Assistant (Feature 2).

Calls Groq Llama 3.3 70B to classify user messages into one of 4 intents.
"""
from __future__ import annotations

import asyncio
import json

from groq import Groq

from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)

_VALID_INTENTS = {"product_search", "recommendation", "comparison", "general"}

_SYSTEM_PROMPT = """\
You are an intent classifier for an Indian e-commerce shopping assistant.

Classify the user message into EXACTLY ONE of these 4 intents:

"product_search" — user asking about a specific product, price, specs, or where to buy.
  Examples: "How much is Samsung S24?", "Is iPhone 15 available on Flipkart?"

"recommendation" — user asking for buying advice or suggestions.
  Examples: "Which phone should I buy?", "Best laptop under 50000?"

"comparison" — user comparing 2 or more specific products.
  Examples: "S24 vs iPhone 15 which is better?", "Compare OnePlus 12 and Pixel 8"

"general" — anything NOT related to buying, comparing, or searching for products.
  Examples: "Hello", "What is 5G?", "Tell me about Samsung company"

Return ONLY a JSON object: {"intent": "<one_of_four_values>"}
No explanation. No extra text. Raw JSON only.
"""


async def classify_intent(message: str) -> str:
    """Classify a user message into one of 4 intents using Groq Llama 3.3 70B.

    Returns one of: "product_search", "recommendation", "comparison", "general".
    Falls back to "product_search" on any failure (safest default).
    """
    try:
        client = Groq(api_key=settings.groq_api_key)

        def _call_groq():
            return client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": message},
                ],
                response_format={"type": "json_object"},
                temperature=0.1,
                max_tokens=50,
            )

        loop = asyncio.get_event_loop()
        resp = await loop.run_in_executor(None, _call_groq)

        raw = resp.choices[0].message.content.strip()
        data = json.loads(raw)
        intent = data.get("intent", "").lower().strip()

        if intent in _VALID_INTENTS:
            logger.info("Intent classified: '%s' → %s", message[:60], intent)
            return intent

        logger.warning(
            "Intent classifier returned invalid value '%s' for '%s' — defaulting to product_search",
            intent, message[:60],
        )
        return "product_search"

    except Exception as e:
        logger.error("Intent classification failed: %s — defaulting to product_search", str(e)[:120])
        return "product_search"
