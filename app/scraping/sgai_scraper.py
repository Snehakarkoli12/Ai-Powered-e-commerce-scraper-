# -*- coding: utf-8 -*-
"""
Core scraping engine: Playwright (stealth) + Groq LLM extraction.

Flow per site:
  1. Launch stealth Chromium context (anti-detection JS injected)
  2. Navigate to search URL, wait for content
  3. Scroll to trigger lazy-loading
  4. Extract visible text with URL markers
  5. Clean + truncate text
  6. Send to Groq LLM for structured extraction
  7. Parse JSON -> RawListing objects

Stealth patches are inline JS (no external dependency needed).
"""
from __future__ import annotations
import asyncio
import json as _json
import re
import time
import random
from typing import List, Tuple, Optional, Dict
from urllib.parse import quote_plus, urlparse

from groq import Groq as _Groq

from app.schemas import RawListing, SiteStatus, SiteStatusCode
from app.marketplaces.registry import marketplace_registry, MarketplaceConfig
from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)


# ── Stealth JS patches ───────────────────────────────────────────────────────
# These patches hide headless Chromium indicators that sites check for.

STEALTH_JS = """
() => {
    // 1. Override navigator.webdriver
    Object.defineProperty(navigator, 'webdriver', { get: () => false });

    // 2. Override navigator.plugins (headless has 0 plugins)
    Object.defineProperty(navigator, 'plugins', {
        get: () => {
            const plugins = [
                { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer' },
                { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai' },
                { name: 'Native Client', filename: 'internal-nacl-plugin' },
            ];
            plugins.length = 3;
            return plugins;
        }
    });

    // 3. Override navigator.languages
    Object.defineProperty(navigator, 'languages', {
        get: () => ['en-IN', 'en-US', 'en'],
    });

    // 4. Override navigator.platform
    Object.defineProperty(navigator, 'platform', {
        get: () => 'Win32',
    });

    // 5. Override navigator.hardwareConcurrency
    Object.defineProperty(navigator, 'hardwareConcurrency', {
        get: () => 8,
    });

    // 6. Override navigator.deviceMemory
    Object.defineProperty(navigator, 'deviceMemory', {
        get: () => 8,
    });

    // 7. Fix chrome runtime
    window.chrome = {
        runtime: { id: undefined },
        loadTimes: function() {},
        csi: function() {},
        app: { isInstalled: false },
    };

    // 8. Override permissions query
    const origQuery = window.navigator.permissions.query;
    window.navigator.permissions.query = (params) =>
        params.name === 'notifications'
            ? Promise.resolve({ state: Notification.permission })
            : origQuery(params);

    // 9. Prevent WebGL renderer detection
    const getParam = WebGLRenderingContext.prototype.getParameter;
    WebGLRenderingContext.prototype.getParameter = function(parameter) {
        if (parameter === 37445) return 'Intel Inc.';
        if (parameter === 37446) return 'Intel Iris OpenGL Engine';
        return getParam.call(this, parameter);
    };

    // 10. Fix toString for overridden functions
    const nativeToString = Function.prototype.toString;
    const origCall = nativeToString.call.bind(nativeToString);
    const hook = new Map();
    function patchToString(fn, str) { hook.set(fn, str); }
    Function.prototype.toString = function() {
        return hook.has(this)
            ? hook.get(this)
            : origCall(this);
    };
    patchToString(Function.prototype.toString, 'function toString() { [native code] }');
}
"""


# ── Per-site configurations ──────────────────────────────────────────────────

# Per-site word budgets for LLM input
_SITE_WORD_BUDGET: Dict[str, int] = {
    "amazon":           1400,
    "flipkart":         1200,
    "meesho":           1000,
    "vijay_sales":      1000,
    "snapdeal":         1000,
    "samsung_shop":     1200,
    "reliance_digital": 1000,
    "croma":            1000,
    "jiomart":          1000,
    "tata_cliq":        1000,
}
_DEFAULT_WORD_BUDGET = 1000
_MAX_OUTPUT_TOKENS   = 2000

# Per-site post-navigation wait times (seconds) — sites with heavy JS need more
_SITE_WAIT: Dict[str, float] = {
    "amazon":           4.0,
    "flipkart":         5.0,
    "meesho":           4.0,
    "samsung_shop":     5.0,
    "tata_cliq":        5.0,
    "croma":            4.0,
    "jiomart":          4.0,
    "reliance_digital": 4.0,
    "snapdeal":         3.0,
    "vijay_sales":      4.0,
}

# User agents to rotate through
_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
]


# ── Groq client (singleton) ─────────────────────────────────────────────────

_groq_client: Optional[_Groq] = None

def _get_groq_client() -> _Groq:
    global _groq_client
    if _groq_client is None:
        _groq_client = _Groq(api_key=settings.groq_api_key)
    return _groq_client


# ── Noise removal patterns ──────────────────────────────────────────────────

_NOISE_PATTERNS = [
    r'(?i)sign\s*in.*?\n',
    r'(?i)log\s*in.*?\n',
    r'(?i)create\s*account.*?\n',
    r'(?i)download\s*the\s*app.*?\n',
    r'(?i)sell\s*on\s*\w+.*?\n',
    r'(?i)become\s*a\s*seller.*?\n',
    r'(?i)customer\s*service.*?\n',
    r'(?i)help\s*center.*?\n',
    r'(?i)cart\s*\(\d*\).*?\n',
    r'(?i)my\s*orders.*?\n',
    r'(?i)all\s*categories.*?\n',
    r'(?i)cookie.*?policy.*?\n',
    r'(?i)privacy.*?policy.*?\n',
    r'(?i)terms.*?conditions.*?\n',
    r'(?i)copyright.*?\n',
    r'(?i)follow\s*us.*?\n',
    r'(?i)\d+\s*results?\s*for.*?\n',
    r'(?i)showing\s*\d+.*?results.*?\n',
    r'(?i)sort\s*by.*?\n',
    r'(?i)filter\s*by.*?\n',
    r'(?i)sponsored\s*\n',
]


def _build_llm_input(page_text: str, word_budget: int) -> str:
    """Clean and truncate page text for LLM. Keeps [URL:...] markers."""
    text = page_text

    # Strip image markers (saves tokens)
    text = re.sub(r'\[IMG:[^\]]{0,500}\]', '', text)

    # Remove noise
    for pattern in _NOISE_PATTERNS:
        text = re.sub(pattern, '\n', text)

    # Collapse whitespace
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r'[ \t]{2,}', ' ', text)

    words = text.split()
    return ' '.join(words[:word_budget])


# ── LLM prompt ──────────────────────────────────────────────────────────────

def _build_prompt(search_query: str, max_results: int) -> str:
    return (
        f"Extract up to {max_results} product listings for '{search_query}' "
        f"from this Indian e-commerce search results page.\n\n"
        f"CRITICAL RULES:\n"
        f"- price_text: The CURRENT SELLING PRICE shown on the page. "
        f"Indian prices use formats like: Rs 55,999 or Rs.1,29,999 or 55,999 or INR 55999. "
        f"Extract the EXACT price string as shown. This is the MOST IMPORTANT field.\n"
        f"- original_price_text: The MRP / strikethrough / crossed-out price if different from selling price. null if not shown.\n"
        f"- listing_url: Extract from [URL:/path/to/product] markers near each product. "
        f"Use the URL that points to a product detail page.\n"
        f"- title: Full product name including brand, model, variant. No 'Add to Cart' text.\n"
        f"- rating_text: Star rating (e.g. '4.3'). null if not shown.\n"
        f"- review_count_text: Number of ratings/reviews. null if not shown.\n"
        f"- delivery_text: Delivery estimate if shown. null if not visible.\n"
        f"- image_url: null (not needed).\n"
        f"- seller_text: Seller name if shown. null if not shown.\n"
        f"- return_policy_text: null.\n\n"
        f"Return REAL products only. Skip accessories, cases, cables unless the query asks for them.\n"
        f"Do NOT hallucinate or invent data. If a field is not visible, use null.\n"
        f"IMPORTANT: You MUST extract price_text for every product. If you see numbers like "
        f"55999 or 55,999 near a product title, that IS the price."
    )


_SYSTEM_PROMPT = (
    "You are an expert product data extractor for Indian e-commerce websites. "
    "You read raw page text and extract structured product data.\n\n"
    "CRITICAL: Indian prices appear as: Rs 55,999 | Rs. 1,29,999 | INR 55999 | "
    "just bare numbers like 55999 near product names. "
    "Indian lakhs format: 1,29,999 means 129999 (one lakh twenty nine thousand).\n\n"
    "Return ONLY a valid JSON object with key 'products' containing an array. "
    "Each product: {title, price_text, original_price_text, rating_text, "
    "review_count_text, delivery_text, listing_url, image_url, seller_text, "
    "return_policy_text}.\n\n"
    "For listing_url: extract from [URL:/some/path] markers in the text.\n"
    "Use null for missing fields. No markdown fences. Raw JSON ONLY."
)


def _run_extraction(text: str, prompt: str, max_output_tokens: int) -> dict:
    """Direct Groq API call for product extraction."""
    client = _get_groq_client()
    user_content = f"{prompt}\n\n--- PAGE TEXT START ---\n{text}\n--- PAGE TEXT END ---"

    resp = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user",   "content": user_content},
        ],
        response_format={"type": "json_object"},
        temperature=0,
        max_tokens=max_output_tokens,
    )

    raw = resp.choices[0].message.content.strip()
    raw = re.sub(r'^```[a-z]*\n?', '', raw)
    raw = re.sub(r'\n?```$', '', raw)

    try:
        data = _json.loads(raw)
        if isinstance(data, list):
            return {"products": data}
        return data
    except _json.JSONDecodeError as e:
        logger.warning("[groq] JSON parse error: %s | raw=%s", e, raw[:200])
        return {"products": []}


# ── Rate limiter ─────────────────────────────────────────────────────────────

class RateLimiter:
    def __init__(self, max_per_minute: int = 25, min_gap_seconds: float = 2.5):
        self._max     = max_per_minute
        self._min_gap = min_gap_seconds
        self._calls:  List[float] = []
        self._lock    = asyncio.Lock()

    async def acquire(self, site_key: str):
        async with self._lock:
            now = time.monotonic()
            self._calls = [t for t in self._calls if now - t < 60.0]
            if len(self._calls) >= self._max:
                wait = 60.0 - (now - self._calls[0]) + 1.0
                logger.info("Rate limit: waiting %.1fs before %s", wait, site_key)
                await asyncio.sleep(wait)
                self._calls = [t for t in self._calls if time.monotonic() - t < 60.0]
            if self._calls:
                gap = time.monotonic() - self._calls[-1]
                if gap < self._min_gap:
                    await asyncio.sleep(self._min_gap - gap + random.uniform(0.1, 0.5))
            self._calls.append(time.monotonic())


_rate_limiter = RateLimiter(max_per_minute=25, min_gap_seconds=2.5)


# ── Playwright stealth fetch ────────────────────────────────────────────────

# Text extraction JS: removes noise elements, injects URL markers, returns text
_EXTRACT_TEXT_JS = """
() => {
    try {
        // Remove non-content elements
        ['script','style','noscript','svg','path','link','meta',
         'iframe','video','audio','canvas'].forEach(tag => {
            document.querySelectorAll(tag).forEach(el => el.remove());
        });

        // Remove hidden elements
        document.querySelectorAll('[style*="display: none"], [style*="display:none"], [hidden]')
            .forEach(el => el.remove());

        // Inject URL markers next to links
        document.querySelectorAll('a[href]').forEach(a => {
            try {
                const href = a.getAttribute('href') || '';
                if (href && href !== '#' && href.length > 3 &&
                    !href.startsWith('javascript:') &&
                    (href.startsWith('/') || href.startsWith('http'))) {
                    const marker = document.createTextNode(' [URL:' + href + '] ');
                    if (a.parentNode) a.parentNode.insertBefore(marker, a.nextSibling);
                }
            } catch(e) {}
        });

        return document.body ? document.body.innerText : '';
    } catch(e) {
        return document.body ? document.body.innerText : '';
    }
}
"""


async def _fetch_html_playwright(url: str, site_key: str, attempt: int = 1) -> str:
    """
    Fetch page text using stealth Chromium.
    Uses anti-detection JS patches, random UA, realistic viewport.
    """
    from playwright.async_api import async_playwright

    html = ""
    ua = random.choice(_USER_AGENTS)
    wait_time = _SITE_WAIT.get(site_key, 3.5)

    try:
        async with async_playwright() as p:
            # Launch with anti-detection args
            browser = await p.chromium.launch(
                headless=settings.playwright_headless,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-features=IsolateOrigins,site-per-process",
                    "--disable-infobars",
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--disable-extensions",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--no-sandbox",
                ],
            )

            ctx = await browser.new_context(
                user_agent=ua,
                viewport={"width": 1366, "height": 768},
                locale="en-IN",
                timezone_id="Asia/Kolkata",
                color_scheme="light",
                java_script_enabled=True,
                bypass_csp=True,
                extra_http_headers={
                    "Accept-Language": "en-IN,en;q=0.9",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Sec-CH-UA": '"Chromium";v="125", "Not.A/Brand";v="24"',
                    "Sec-CH-UA-Mobile": "?0",
                    "Sec-CH-UA-Platform": '"Windows"',
                    "Sec-Fetch-Dest": "document",
                    "Sec-Fetch-Mode": "navigate",
                    "Sec-Fetch-Site": "none",
                    "Sec-Fetch-User": "?1",
                    "Upgrade-Insecure-Requests": "1",
                },
            )

            # Inject stealth patches BEFORE any navigation
            await ctx.add_init_script(STEALTH_JS)

            page = await ctx.new_page()

            # Block heavy resources to speed up
            await page.route(
                "**/*",
                lambda route: route.abort()
                if route.request.resource_type in ("font", "media")
                else route.continue_(),
            )

            logger.info("[%s] Navigating (attempt %d): %s", site_key, attempt, url[:80])

            await page.goto(url, wait_until="domcontentloaded", timeout=30000)

            # Wait for JS hydration
            await asyncio.sleep(wait_time + random.uniform(0.5, 1.5))

            # Scroll down slowly (mimics human) to trigger lazy-loaded products
            for scroll_pct in [0.3, 0.5, 0.7, 0.9]:
                await page.evaluate(
                    f"window.scrollTo(0, document.body.scrollHeight * {scroll_pct})"
                )
                await asyncio.sleep(0.5 + random.uniform(0.2, 0.6))

            # Scroll back up a bit (human behavior)
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight * 0.2)")
            await asyncio.sleep(0.5)

            # Extract text with URL markers
            html = await page.evaluate(_EXTRACT_TEXT_JS)

            logger.info("[%s] Fetched %d chars of page text", site_key, len(html))

            await browser.close()

    except Exception as e:
        logger.error("[%s] Playwright fetch error: %s", site_key, str(e)[:150])

    return html


# ── URL / field cleaners ────────────────────────────────────────────────────

_FAKE_DOMAINS = {
    "example.com", "placeholder.com", "domain.com",
    "website.com", "url.com", "product.com", "test.com",
}
_NULL_VALS = {
    "none", "null", "n/a", "na", "", "not available",
    "not found", "not visible", "[url]", "[img]",
    "not shown", "not present", "undefined",
}


def _clean_url(raw: Optional[str], base_url: str) -> str:
    if not raw:
        return ""
    raw = raw.strip()
    if raw.lower() in _NULL_VALS:
        return ""
    if raw.startswith("[URL:"):
        raw = raw[5:].rstrip("]").strip()
    if not raw or raw.lower() == "[url]":
        return ""
    try:
        domain = urlparse(raw).netloc.lower().replace("www.", "")
        if domain in _FAKE_DOMAINS:
            return ""
    except Exception:
        return ""
    if raw.startswith("http"):
        return raw
    if raw.startswith("/"):
        return base_url.rstrip("/") + raw
    return ""


def _get_field(item, key: str) -> Optional[str]:
    v = item.get(key) if isinstance(item, dict) else getattr(item, key, None)
    if v is None:
        return None
    s = str(v).strip()
    return None if s.lower() in _NULL_VALS else s


# ── Result parser ────────────────────────────────────────────────────────────

def _parse_result(result: dict, config: MarketplaceConfig) -> List[RawListing]:
    raw_products = []
    if isinstance(result, dict):
        raw_products = result.get("products", [])
        if not raw_products:
            for val in result.values():
                if isinstance(val, list) and val:
                    raw_products = val
                    break
    elif isinstance(result, list):
        raw_products = result

    listings = []
    for item in raw_products:
        title = _get_field(item, "title")
        if not title or len(title) < 5:
            continue

        listing_url = _clean_url(_get_field(item, "listing_url"), config.base_url)

        price_raw = _get_field(item, "price_text")
        if not price_raw:
            logger.warning("[%s] No price for: %s", config.key, title[:50])

        listings.append(RawListing(
            platform_key=config.key,
            listing_url=listing_url,
            title=title,
            price_text=price_raw,
            original_price_text=_get_field(item, "original_price_text"),
            rating_text=_get_field(item, "rating_text"),
            review_count_text=_get_field(item, "review_count_text"),
            delivery_text=_get_field(item, "delivery_text"),
            shipping_text=None,
            seller_text=_get_field(item, "seller_text"),
            return_policy_text=_get_field(item, "return_policy_text"),
            image_url=_get_field(item, "image_url"),
        ))

    return listings


# ── Per-site scraper ─────────────────────────────────────────────────────────

async def scrape_one_site(
    config: MarketplaceConfig,
    search_query: str,
    max_results: int,
) -> Tuple[List[RawListing], SiteStatus]:

    status = SiteStatus(
        marketplace_key=config.key,
        marketplace_name=config.name,
        status=SiteStatusCode.PENDING,
        message="Starting",
        listings_found=0,
    )

    url = config.search_url_pattern.format(query=quote_plus(search_query))
    logger.info("[%s] Starting: %s", config.key, url[:80])

    # Try up to 2 attempts (fresh browser context each time)
    for attempt in range(1, 3):
        try:
            raw_text = await _fetch_html_playwright(url, config.key, attempt)

            if not raw_text or len(raw_text.strip()) < 100:
                status.status  = SiteStatusCode.NO_RESULTS
                status.message = f"Empty page from {config.name} (attempt {attempt})"
                if attempt < 2:
                    logger.info("[%s] Empty page, retrying...", config.key)
                    await asyncio.sleep(random.uniform(2.0, 4.0))
                    continue
                return [], status

            # Check for bot challenge
            bot_phrases = config.bot_detection_phrases or []
            text_lower = raw_text.lower()
            bot_found = None
            for phrase in bot_phrases:
                if phrase.lower() in text_lower:
                    bot_found = phrase
                    break

            if bot_found:
                status.status  = SiteStatusCode.BOT_CHALLENGE
                status.message = f"Bot challenge on {config.name}: '{bot_found}'"
                logger.warning("[%s] Bot challenge (attempt %d): '%s'", config.key, attempt, bot_found)
                if attempt < 2:
                    await asyncio.sleep(random.uniform(3.0, 6.0))
                    continue
                return [], status

            # Prepare LLM input
            word_budget = _SITE_WORD_BUDGET.get(config.key, _DEFAULT_WORD_BUDGET)
            text = _build_llm_input(raw_text, word_budget)
            word_count = len(text.split())
            logger.info("[%s] LLM input: %d words (budget: %d)", config.key, word_count, word_budget)

            # Rate limit before Groq call
            await _rate_limiter.acquire(config.key)

            # LLM extraction
            prompt = _build_prompt(search_query, max_results)
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None, _run_extraction, text, prompt, _MAX_OUTPUT_TOKENS
            )

            listings = _parse_result(result, config)

            with_price = sum(1 for l in listings if l.price_text)
            logger.info(
                "[%s] Extracted %d listings (%d with price)",
                config.key, len(listings), with_price,
            )

            if listings:
                status.status = SiteStatusCode.OK
                status.message = f"{len(listings)} listings ({with_price} with price)"
                status.listings_found = len(listings)
                return listings, status
            else:
                status.status = SiteStatusCode.NO_RESULTS
                status.message = f"LLM found 0 products on {config.name}"
                if attempt < 2:
                    logger.info("[%s] 0 listings, retrying...", config.key)
                    await asyncio.sleep(random.uniform(2.0, 4.0))
                    continue
                return [], status

        except Exception as err:
            err_str   = str(err)
            err_lower = err_str.lower()

            if any(k in err_lower for k in ["401", "invalid api key", "authentication"]):
                status.status  = SiteStatusCode.ERROR
                status.message = "Invalid Groq API key"
                return [], status  # Don't retry auth errors
            elif any(k in err_lower for k in ["413", "request too large"]):
                status.status  = SiteStatusCode.ERROR
                status.message = f"Token limit on {config.name}"
                return [], status
            elif any(k in err_lower for k in ["rate limit", "429", "quota", "too many"]):
                status.status  = SiteStatusCode.ERROR
                status.message = "Groq rate limit - retry in 60s"
                if attempt < 2:
                    await asyncio.sleep(30.0)
                    continue
                return [], status
            elif any(k in err_lower for k in ["timeout", "timed out"]):
                status.status  = SiteStatusCode.TIMEOUT
                status.message = f"Timeout on {config.name}"
            else:
                status.status  = SiteStatusCode.ERROR
                status.message = f"Error: {err_str[:100]}"

            logger.error("[%s] Failed (attempt %d): %s", config.key, attempt, err_str[:120])
            if attempt < 2:
                await asyncio.sleep(random.uniform(2.0, 4.0))

    return [], status


# ── Orchestrator ─────────────────────────────────────────────────────────────

_BROWSER_SEMAPHORE: Optional[asyncio.Semaphore] = None

def _get_browser_semaphore() -> asyncio.Semaphore:
    global _BROWSER_SEMAPHORE
    if _BROWSER_SEMAPHORE is None:
        _BROWSER_SEMAPHORE = asyncio.Semaphore(3)
    return _BROWSER_SEMAPHORE


async def _scrape_with_semaphore(
    config: MarketplaceConfig,
    search_query: str,
    max_results: int,
) -> Tuple[List[RawListing], SiteStatus]:
    sem = _get_browser_semaphore()
    async with sem:
        return await scrape_one_site(config, search_query, max_results)


async def run_sgai_orchestrator(
    search_query:         str,
    marketplace_keys:     List[str],
    max_results_per_site: int = 5,
) -> Tuple[List[RawListing], List[SiteStatus]]:

    logger.info(
        "Orchestrator: '%s' | %d sites: %s",
        search_query, len(marketplace_keys), marketplace_keys,
    )

    configs = [
        c for k in marketplace_keys
        if (c := marketplace_registry.get(k)) and c.enabled
    ]

    if not configs:
        logger.error("No enabled configs for keys: %s", marketplace_keys)
        return [], []

    # Run all sites in parallel (semaphore limits concurrent browsers to 3)
    tasks = [
        _scrape_with_semaphore(cfg, search_query, max_results_per_site)
        for cfg in configs
    ]

    results = await asyncio.gather(*tasks, return_exceptions=True)

    all_listings: List[RawListing] = []
    all_statuses: List[SiteStatus] = []

    for cfg, result in zip(configs, results):
        if isinstance(result, Exception):
            logger.error("[%s] Exception: %s", cfg.key, result)
            all_statuses.append(SiteStatus(
                marketplace_key=cfg.key,
                marketplace_name=cfg.name,
                status=SiteStatusCode.ERROR,
                message=f"Exception: {str(result)[:80]}",
                listings_found=0,
            ))
        else:
            listings, site_status = result
            all_listings.extend(listings)
            all_statuses.append(site_status)

    ok = sum(1 for s in all_statuses if s.listings_found > 0)
    logger.info(
        "Orchestrator done: %d total listings from %d/%d sites",
        len(all_listings), ok, len(all_statuses),
    )
    return all_listings, all_statuses
