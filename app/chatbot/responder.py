# -*- coding: utf-8 -*-
"""
Step 3 — LLM Response Generator for Chatbot Assistant (Feature 2).

Builds context-aware prompts and calls Groq Llama 3.3 70B
to generate conversational shopping assistant responses.
"""
from __future__ import annotations

import asyncio
from typing import List

from groq import Groq

from app.chatbot.schemas import ShoppingResult
from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)

_SYSTEM_PROMPT = (
    "You are a helpful, knowledgeable shopping assistant "
    "for Indian consumers. You speak in simple English, "
    "reference all prices in Indian Rupees (₹), and always "
    "aim to help users find the best value for their money. "
    "Be friendly, concise, and helpful."
)

_FALLBACK_RESPONSE = "I'm having trouble right now. Please try again in a moment."


def _format_products_context(products: List[ShoppingResult]) -> str:
    """Format product data as text context for the LLM."""
    lines = []
    for i, p in enumerate(products[:10], 1):
        parts = [f"{i}. {p.title}"]
        if p.price:
            parts.append(f"Price: {p.price}")
        if p.rating is not None:
            parts.append(f"Rating: {p.rating}/5")
        if p.reviews is not None:
            parts.append(f"Reviews: {p.reviews}")
        if p.source:
            parts.append(f"Store: {p.source}")
        if p.delivery:
            parts.append(f"Delivery: {p.delivery}")
        lines.append(" | ".join(parts))
    return "\n".join(lines)


def _build_user_prompt(
    message: str,
    products: List[ShoppingResult],
    intent: str,
) -> str:
    """Build the user prompt based on intent and product availability."""

    product_context = _format_products_context(products) if products else ""

    # CASE 4: general intent (no products needed)
    if intent == "general":
        return (
            f"User question: {message}\n\n"
            "Answer this general question conversationally using your knowledge. "
            "No product recommendations unless the user specifically asked. "
            "Keep your response under 150 words."
        )

    # CASE 5: products empty AND intent != general (SerpAPI failed)
    if not products:
        return (
            f"User question: {message}\n\n"
            "Unfortunately, no product results were found for this query. "
            "Apologize briefly, suggest the user try the main comparison tool "
            "for detailed price comparison, and suggest they try a more specific search query. "
            "Keep your response under 80 words."
        )

    # CASE 2: comparison intent with products
    if intent == "comparison":
        return (
            f"User question: {message}\n\n"
            f"Product data from Google Shopping India:\n{product_context}\n\n"
            "Compare the top 2 products side by side. "
            "Highlight the price difference in ₹. "
            "Compare their ratings. "
            "State which is better and for whom. "
            "Keep your response under 150 words. Sound conversational, not like a data list."
        )

    # CASE 3: recommendation intent with products
    if intent == "recommendation":
        return (
            f"User question: {message}\n\n"
            f"Product data from Google Shopping India:\n{product_context}\n\n"
            "Give ONE strong recommendation only. "
            "Explain exactly why it's the best choice. "
            "Mention price in ₹ and rating. "
            "Keep your response under 100 words. Sound conversational."
        )

    # CASE 1: product_search (or any other intent) with products
    return (
        f"User question: {message}\n\n"
        f"Product data from Google Shopping India:\n{product_context}\n\n"
        "Acknowledge the user's question directly. "
        "Present the top 2-3 products from the data above. "
        "Include price in ₹ for each product. "
        "Mention rating and source (where to buy). "
        "End with a clear single recommendation. "
        "Keep your response under 150 words. Sound conversational, NOT like a data list."
    )


async def generate_response(
    message: str,
    chat_history: List[dict],
    products: List[ShoppingResult],
    intent: str,
) -> str:
    """Generate a conversational response using Groq Llama 3.3 70B.

    Returns a clean text string. On failure, returns a safe fallback message.
    """
    try:
        client = Groq(api_key=settings.groq_api_key)

        # Build messages array: system → last 4 history → current user prompt
        messages = [{"role": "system", "content": _SYSTEM_PROMPT}]

        # Add last 4 messages from chat history
        recent_history = chat_history[-4:] if chat_history else []
        for msg in recent_history:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": content})

        # Build and append current user prompt
        user_prompt = _build_user_prompt(message, products, intent)
        messages.append({"role": "user", "content": user_prompt})

        def _call_groq():
            return client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=messages,
                temperature=0.7,
                max_tokens=300,
            )

        loop = asyncio.get_event_loop()
        resp = await loop.run_in_executor(None, _call_groq)

        response_text = resp.choices[0].message.content.strip()
        logger.info(
            "Responder: generated %d chars for intent=%s",
            len(response_text), intent,
        )
        return response_text

    except Exception as e:
        logger.error("Responder LLM call failed: %s", str(e)[:150])
        return _FALLBACK_RESPONSE
