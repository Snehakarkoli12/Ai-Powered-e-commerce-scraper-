# -*- coding: utf-8 -*-
"""
Step 4 — Chatbot Service Orchestrator (Feature 2).

Calls intent → search → responder sequentially.
Pure Python async — no frameworks.
"""
from __future__ import annotations

from app.chatbot.schemas import ChatRequest, ChatResponse
from app.chatbot.intent import classify_intent
from app.chatbot.search import fetch_shopping_results
from app.chatbot.responder import generate_response
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def run_chatbot(request: ChatRequest) -> ChatResponse:
    """Orchestrate the 3-step chatbot pipeline.

    Step 1: Classify intent (Groq LLM)
    Step 2: Fetch shopping results (SerpAPI)
    Step 3: Generate response (Groq LLM)

    Returns ChatResponse. Never raises — catches all errors.
    """
    try:
        # Step 1: classify intent
        intent = await classify_intent(request.message)

        # Step 2: fetch shopping results
        products = await fetch_shopping_results(request.message, intent)

        # Step 3: generate response
        response = await generate_response(
            request.message,
            request.chat_history,
            products,
            intent,
        )

        return ChatResponse(
            message=response,
            products=products,
            source="google_shopping",
            intent=intent,
        )

    except Exception as e:
        logger.error("Chatbot service error: %s", str(e)[:150])
        return ChatResponse(
            message="Something went wrong. Please try again.",
            products=[],
            source="google_shopping",
            intent="general",
        )
