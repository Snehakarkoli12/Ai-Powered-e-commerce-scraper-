from __future__ import annotations
import os
from typing import List
from dotenv import load_dotenv

load_dotenv()

class Settings:
    debug:               bool       = os.getenv("DEBUG", "False").lower() == "true"
    playwright_headless: bool       = os.getenv("PLAYWRIGHT_HEADLESS", "True").lower() == "true"
    log_level:           str        = os.getenv("LOG_LEVEL", "INFO").upper()
    allowed_origins:     List[str]  = [
        s.strip() for s in
        os.getenv("ALLOWED_ORIGINS", "http://127.0.0.1:8000,http://localhost:5173").split(",")
        if s.strip()
    ]
    # LLM
    llm_enabled:         bool = os.getenv("LLM_ENABLED", "true").lower() == "true"
    groq_api_key:        str  = os.getenv("GROQ_API_KEY", "")
    groq_primary_model:  str  = os.getenv("GROQ_PRIMARY_MODEL", "llama-3.3-70b-versatile")
    groq_fast_model:     str  = os.getenv("GROQ_FAST_MODEL", "llama-3.1-8b-instant")
    llm_max_concurrent:  int  = int(os.getenv("LLM_MAX_CONCURRENT", "3"))
    # Paths
    marketplaces_dir:    str  = os.path.join(
        os.path.dirname(__file__), "marketplaces", "configs"
    )

settings = Settings()
