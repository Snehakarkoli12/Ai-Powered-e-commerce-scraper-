# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import List, Any
from pydantic import field_validator
from pydantic_settings import BaseSettings
from pydantic.fields import FieldInfo


class Settings(BaseSettings):

    # ── Groq LLM ─────────────────────────────────────────────────────────────
    groq_api_key:       str  = ""
    groq_primary_model: str  = "llama-3.3-70b-versatile"
    groq_fast_model:    str  = "llama-3.1-8b-instant"
    llm_enabled:        bool = True
    llm_max_concurrent: int  = 3

    # ── Browser ───────────────────────────────────────────────────────────────
    playwright_headless: bool = False

    # ── Marketplaces ─────────────────────────────────────────────────────────
    marketplaces_dir: str = "app/marketplaces/configs"

    # ── CORS ─────────────────────────────────────────────────────────────────
    allowed_origins: List[str] = [
        "http://127.0.0.1:8000",
        "http://localhost:8000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]

    # ── App ───────────────────────────────────────────────────────────────────
    debug:     bool = False
    log_level: str  = "INFO"

    # ── Validator: accept both JSON array AND comma-separated string ──────────
    @field_validator("allowed_origins", mode="before")
    @classmethod
    def parse_origins(cls, v: Any) -> List[str]:
        if isinstance(v, list):
            return v
        if isinstance(v, str):
            v = v.strip()
            # JSON array format: ["a","b"]
            if v.startswith("["):
                import json
                return json.loads(v)
            # Comma-separated format: a,b,c
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    class Config:
        env_file          = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
