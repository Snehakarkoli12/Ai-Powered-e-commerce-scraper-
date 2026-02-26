Here is the complete detailed summary of everything built, solved, and pending in this session.

***

# Agentic Price Browser — Complete Project Summary

## What We Built

A **local, free, AI-powered multi-agent price comparison system** for Indian e-commerce. It accepts a product query, scrapes 10+ marketplaces in parallel using real browser automation, normalizes and matches listings using LLM intelligence, ranks them by user preference, and returns structured JSON with an AI-generated recommendation.

***

## Tech Stack

| Layer | Technology | Purpose |
|---|---|---|
| **Backend API** | FastAPI + Uvicorn | Async REST API server |
| **Browser Automation** | Playwright (Chromium) | Real browser scraping |
| **Stealth** | `playwright-stealth` + custom JS | Bypass bot detection  [scrapeless](https://www.scrapeless.com/en/blog/avoid-bot-detection-with-playwright-stealth) |
| **LLM** | Groq API (`llama-3.3-70b-versatile` + `llama-3.1-8b-instant`) | Query parsing, selector discovery, matching, explanation |
| **Config** | YAML per marketplace | Dynamic site registry |
| **Validation** | Pydantic v2 | Request/response schemas |
| **Dev Reload** | `watchfiles.run_process` | Hot reload on Windows |
| **Frontend** | React + Vite + Tailwind CSS | Search UI |
| **Language** | Python 3.11 | Core runtime |

***

## Full System Architecture

```
USER REQUEST (query / product URL)
         │
         ▼
┌─────────────────────────────────────────────────────┐
│                  FastAPI Server                      │
│          POST /api/compare                          │
│          POST /api/debug/compare                    │
│          GET  /api/health/scrapers                  │
└─────────────────────────┬───────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────┐
│              5-Stage Agent Pipeline                  │
│                                                     │
│  Stage 1: PLANNER                                   │
│  ┌──────────────────────────────────────────────┐   │
│  │ LLM (llama-3.3-70b) parses query →           │   │
│  │ brand / model / storage / color / category   │   │
│  │ Falls back to regex if LLM fails             │   │
│  │ Selects marketplaces (brand affinity filter) │   │
│  └──────────────────────────────────────────────┘   │
│                          │                          │
│  Stage 2: SCRAPER        ▼                          │
│  ┌──────────────────────────────────────────────┐   │
│  │ asyncio.gather → all 10 sites in parallel    │   │
│  │ Per site: Playwright opens real browser      │   │
│  │ Stealth JS + per-domain context isolation    │   │
│  │ Bot challenge → reset context → retry once   │   │
│  │ Selector: YAML → universal → LLM discovery  │   │
│  │ Saves debug HTML for every failure           │   │
│  └──────────────────────────────────────────────┘   │
│                          │                          │
│  Stage 3: EXTRACTOR      ▼                          │
│  ┌──────────────────────────────────────────────┐   │
│  │ Parse price/rating/delivery from raw text    │   │
│  │ LLM enriches cards missing price field       │   │
│  │ Compute effective_price = disc - coupon      │   │
│  └──────────────────────────────────────────────┘   │
│                          │                          │
│  Stage 4: MATCHER        ▼                          │
│  ┌──────────────────────────────────────────────┐   │
│  │ Regex brand/model/storage/color scoring      │   │
│  │ LLM called for uncertain scores (0.3–0.75)   │   │
│  │ Hard reject: model number mismatch           │   │
│  │ Accessory keyword filter                     │   │
│  │ Deduplication by (platform, price)           │   │
│  └──────────────────────────────────────────────┘   │
│                          │                          │
│  Stage 5: RANKER         ▼                          │
│  ┌──────────────────────────────────────────────┐   │
│  │ Score breakdown: price / delivery / trust    │   │
│  │ 4 modes: cheapest/fastest/reliable/balanced  │   │
│  │ Badge assignment: Top Pick / Lowest / Fastest│   │
│  │ LLM generates explanation + tradeoffs        │   │
│  └──────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────┘
                          │
                          ▼
        Structured JSON response with offers,
        site_statuses, explanation, score_breakdown
```

***

## File Structure Built

```
app/
├── main.py                        ← FastAPI app, lifespan, all routes
├── config.py                      ← Settings from .env
├── schemas.py                     ← All Pydantic models
├── __init__.py                    ← Empty (critical)
│
├── agents/
│   ├── __init__.py                ← PipelineState dataclass
│   ├── planner.py                 ← Stage 1: LLM + regex query parsing
│   ├── scraper.py                 ← Stage 2: orchestrator wrapper
│   ├── extractor.py               ← Stage 3: price/field normalization
│   ├── matcher.py                 ← Stage 4: product match scoring
│   ├── ranker.py                  ← Stage 5: ranking + badges + explanation
│   ├── llm_extractor.py           ← LLM: enrich missing fields + discover selectors
│   ├── llm_matcher.py             ← LLM: semantic match scoring
│   └── llm_ranker.py              ← LLM: explanation generation
│
├── scraping/
│   ├── __init__.py                ← Empty (critical)
│   ├── base.py                    ← BaseScraper: full Playwright lifecycle
│   ├── orchestrator.py            ← asyncio.gather across all sites
│   ├── playwright_manager.py      ← Singleton browser, stealth, per-domain contexts
│   ├── selector_engine.py         ← Multi-strategy selector resolution + caching
│   ├── amazon.py / flipkart.py    ← Per-site scraper subclasses
│   ├── croma.py / jiomart.py      ← (all extend BaseScraper)
│   └── debug/                     ← Auto-saved HTML snapshots on failures
│
├── marketplaces/
│   ├── registry.py                ← YAML loader, MarketplaceConfig dataclass
│   └── configs/
│       ├── amazon.yaml            ← 10 marketplace configs
│       ├── flipkart.yaml
│       └── ... (croma, jiomart, meesho, reliance_digital,
│               snapdeal, tata_cliq, vijay_sales, samsung_shop)
│
└── utils/
    ├── llm_client.py              ← Groq client, JSON completion, fast model toggle
    └── logger.py                  ← Structured logging

run.py                             ← Entry point with watchfiles hot-reload
frontend/                          ← React + Vite + Tailwind SPA
```

***

## Issues Solved (Chronological)

### 1. `NotImplementedError` — Playwright on Windows
- **Cause:** Windows `WindowsSelectorEventLoopPolicy` blocks `subprocess_exec`. Uvicorn with `reload=True` forces SelectorLoop internally. [github](https://github.com/zauberzeug/nicegui/issues/3874)
- **Fix:** `run.py` uses `watchfiles.run_process(_server)` where `_server()` sets `WindowsProactorEventLoopPolicy` **before** calling `uvicorn.run(..., loop="none")`.

### 2. `0 raw_listings`, `site_statuses: []`, `0.2s response`
- **Cause:** `app/scraping/__init__.py` and `app/__init__.py` had old-codebase imports causing `ImportError` on every `importlib.import_module("app.scraping.X")`. The `_scrape_one()` exception handler was returning `([], None, key, "")` — `None` status was silently dropped by the `if status:` guard.
- **Fix:** Wiped both `__init__.py` files to empty. Rewrote `_scrape_one()` to **always** return a proper `SiteStatus` — never `None`.

### 3. `ImportError: cannot import name 'run_planner'`
- **Cause:** All 5 agent files (`planner.py`, `scraper.py`, `extractor.py`, `matcher.py`, `ranker.py`) were old versions from a previous codebase phase with wrong function names and signatures.
- **Fix:** Complete rewrite of all 5 agent files with correct async function signatures matching `app/main.py` imports.

### 4. `invalid syntax (base.py, line 224)` → `0/9 importable`
- **Cause:** Unicode characters (`→`, `──`, `—`) in f-strings and comments got corrupted during copy-paste from chat to Windows editor.
- **Fix:** Rewrote `base.py` using 100% ASCII-safe string concatenation instead of f-strings with special characters.

### 5. `expected 'except' or 'finally' block (base.py, line 97)` → `0/9 importable`
- **Cause:** The bot-challenge retry snippet from Fix 2 was pasted as a **partial snippet** inside the existing `try` block, creating an orphaned nested `try` without a matching `except`.
- **Fix:** Provided the complete `base.py` as a single coherent file — the bot retry block is a proper `if` branch inside the main `try`, not a new `try`.

### 6. `HARD_REJECT(model_mismatch)` — iPhone Air scraped instead of iPhone 15
- **Cause:** Amazon search URL without sort parameter returned newest/featured items first (iPhone Air was new at time of test).
- **Fix:** Changed Amazon `search_url_pattern` to `&s=review-rank` to sort by reviews, pushing established products to top.

### 7. `Reliance Digital timeout (25s)`
- **Cause:** `wait_strategy: "networkidle"` in YAML — Reliance Digital JS never fully settles so networkidle never fires.
- **Fix:** Changed to `wait_strategy: "domcontentloaded"` in YAML.

### 8. `asyncio.Semaphore` module-level creation risk
- **Cause:** `_SEMAPHORE = asyncio.Semaphore(4)` at module import time can bind to wrong event loop.
- **Fix:** Changed to lazy initialization via `_get_semaphore()` function, called only inside async context.

***

## Issues Still Present / Not Fully Resolved

### ⚠️ 1. Bot Challenge on 5 Sites (Major)
Flipkart, Croma, JioMart, Meesho, Tata CLiQ are returning `bot_challenge` even with stealth JS. [scrapeless](https://www.scrapeless.com/en/blog/avoid-bot-detection-with-playwright-stealth)

```
Root cause: Cloudflare / custom bot detection fingerprints headless Chromium
Status:     Retry-with-reset-context implemented but may still fail
Remaining:  Sites using Cloudflare Turnstile or advanced TLS fingerprinting
            require proxy rotation or residential IPs to fully bypass
Next fix:   Set PLAYWRIGHT_HEADLESS=False in .env (headed mode bypasses most)
            OR integrate free proxy list rotation in playwright_manager.py
```

### ⚠️ 2. Snapdeal `selector_error`
```
Root cause: Snapdeal's DOM structure doesn't match any of the 21 universal
            patterns or the YAML selectors. LLM discovery ran but failed.
Status:     Debug HTML saved at app/scraping/debug/snapdeal_no_container_*.html
Next fix:   Open that HTML file, find the real product card selector,
            update snapdeal.yaml selectors.search_results_container
```

### ⚠️ 3. Vijay Sales `0 listings` (selectors stale)
```
Root cause: Class names in vijay_sales.yaml don't match current live DOM
Status:     Container found, but sub-selectors (title/price) produce no text
Next fix:   Open site in browser DevTools, inspect product card classes,
            update vijay_sales.yaml with real class names
```

### ⚠️ 4. Tata CLiQ Missing from Tests
```
Root cause: Not confirmed tested yet. Likely bot_challenge (Cloudflare)
Next fix:   Same as point 1 — headed mode + delay increase
```

### ⚠️ 5. `delivery_days_max: null` Everywhere
```
Root cause: Delivery text selectors not matching, delivery info is
            often behind login or pincode modal on Indian sites
Status:     LLM enrichment fills this for cards with no delivery text
Next fix:   Add pincode pre-fill step in base.py _wait_for_content()
            (inject a default Mumbai/Delhi pincode via JS before scraping)
```

### ⚠️ 6. Frontend Not Connected to Live API
```
Status:     React + Vite + Tailwind scaffold provided and written
            but not confirmed running alongside backend
Next fix:   cd frontend && npm install && npm run dev
            Then test at http://localhost:5173
```

***

## Current Working State

```
✅ Server starts cleanly          python run.py
✅ Playwright starts              headless Chromium ready
✅ LLM connected                  Groq llama-3.3-70b-versatile
✅ 11 marketplaces loaded         from YAML registry
✅ All scrapers importable        /api/health/scrapers → 9/9 ok
✅ Pipeline executes              ~30-40s real scraping
✅ Amazon scraping                1-5 listings returned
✅ Vijay Sales                    container found
✅ Query parsing                  LLM extracts brand/model/storage correctly
✅ Match scoring                  regex + LLM hybrid scoring
✅ Ranking                        4 modes working
✅ Explanation                    LLM-generated text
⚠️  5 sites bot-challenged        need headed mode or proxies
⚠️  Snapdeal selector broken      needs YAML update from live DOM
⚠️  Delivery data sparse          pincode modal blocking
⏳ Frontend                       code ready, npm install needed
```