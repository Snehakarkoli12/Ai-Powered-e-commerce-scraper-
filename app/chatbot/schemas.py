# -*- coding: utf-8 -*-
"""
Pydantic V2 schemas for Chatbot Assistant (Feature 2).
Completely independent from Feature 1 schemas.
"""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


class ChatRequest(BaseModel):
    """Incoming chat message from the user."""

    message: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="User's current question",
    )
    chat_history: List[dict] = Field(
        default_factory=list,
        description='Previous messages: [{"role": "user"|"assistant", "content": "..."}]',
    )

    @field_validator("chat_history", mode="before")
    @classmethod
    def trim_history(cls, v: List[dict]) -> List[dict]:
        """Keep only the last 20 messages."""
        if isinstance(v, list) and len(v) > 20:
            return v[-20:]
        return v


class ShoppingResult(BaseModel):
    """A single product card returned from SerpAPI Google Shopping."""

    title: str
    price: Optional[str] = None
    rating: Optional[float] = None
    reviews: Optional[int] = None
    source: Optional[str] = None
    delivery: Optional[str] = None
    thumbnail: Optional[str] = None
    link: Optional[str] = None

    @field_validator("reviews", mode="before")
    @classmethod
    def coerce_reviews(cls, v):
        """SerpAPI sometimes returns reviews as float (e.g., 3523.0)."""
        if v is None:
            return None
        try:
            return int(v)
        except (ValueError, TypeError):
            return None


class ChatResponse(BaseModel):
    """Response sent back to the frontend."""

    message: str = Field(
        ...,
        description="LLM-generated response text",
    )
    products: List[ShoppingResult] = Field(
        default_factory=list,
        description="Product cards from SerpAPI",
    )
    source: str = Field(
        default="google_shopping",
        description="Data source identifier (always google_shopping)",
    )
    intent: str = Field(
        ...,
        description="Classified intent for frontend use",
    )
