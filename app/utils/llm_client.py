from __future__ import annotations
import asyncio, json, re
from functools import partial
from typing import Optional, Dict
from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)


class GroqLLMClient:
    """
    Unified Groq client.
    - primary_model (70B): query parsing, matching, selector discovery, explanation
    - fast_model    (8B): per-card extraction (many parallel calls)
    Semaphore respects Groq free-tier: 30 req/min → max 3 concurrent
    """

    def __init__(self):
        self.enabled       = settings.llm_enabled and bool(settings.groq_api_key)
        self.primary_model = settings.groq_primary_model
        self.fast_model    = settings.groq_fast_model
        self._client       = None
        self._semaphore    = None   # lazily initialized (needs running event loop)

        if self.enabled:
            logger.info(f"✓ Groq LLM | primary={self.primary_model} | fast={self.fast_model}")
        else:
            logger.warning("⚠ LLM disabled — set GROQ_API_KEY + LLM_ENABLED=true in .env")

    def _get_semaphore(self):
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(settings.llm_max_concurrent)
        return self._semaphore

    def _get_client(self):
        if not self._client:
            from groq import Groq
            self._client = Groq(api_key=settings.groq_api_key)
        return self._client

    async def complete_json(
        self,
        system:         str,
        user:           str,
        use_fast_model: bool = False,
    ) -> Optional[Dict]:
        if not self.enabled:
            return None

        model = self.fast_model if use_fast_model else self.primary_model

        async with self._get_semaphore():
            try:
                loop     = asyncio.get_event_loop()
                client   = self._get_client()
                response = await loop.run_in_executor(
                    None,
                    partial(
                        client.chat.completions.create,
                        model=model,
                        messages=[
                            {"role": "system", "content": system},
                            {"role": "user",   "content": user},
                        ],
                        response_format={"type": "json_object"},
                        temperature=0.0,
                        max_tokens=1024,
                    )
                )
                raw = response.choices[0].message.content
                return self._parse_json(raw)

            except Exception as e:
                err = str(e)
                logger.error(f"Groq JSON [{model}]: {err[:80]}")
                if "rate_limit" in err.lower() or "429" in err:
                    await asyncio.sleep(5)
                return None

    async def complete_text(
        self,
        system:         str,
        user:           str,
        use_fast_model: bool = False,
        max_tokens:     int  = 256,
    ) -> Optional[str]:
        if not self.enabled:
            return None

        model = self.fast_model if use_fast_model else self.primary_model

        async with self._get_semaphore():
            try:
                loop     = asyncio.get_event_loop()
                client   = self._get_client()
                response = await loop.run_in_executor(
                    None,
                    partial(
                        client.chat.completions.create,
                        model=model,
                        messages=[
                            {"role": "system", "content": system},
                            {"role": "user",   "content": user},
                        ],
                        temperature=0.2,
                        max_tokens=max_tokens,
                    )
                )
                return response.choices[0].message.content.strip()
            except Exception as e:
                logger.error(f"Groq text [{model}]: {str(e)[:80]}")
                return None

    def _parse_json(self, text: str) -> Optional[Dict]:
        if not text:
            return None
        try:
            clean = re.sub(r'```(?:json)?\s*', '', text).strip().rstrip('`')
            return json.loads(clean)
        except Exception:
            m = re.search(r'\{[\s\S]+\}', text)
            if m:
                try:
                    return json.loads(m.group(0))
                except Exception:
                    pass
        return None


llm_client = GroqLLMClient()
