# -*- coding: utf-8 -*-
from __future__ import annotations
import asyncio
import random
from typing import Optional, Dict

from playwright.async_api import (
    async_playwright, Browser, BrowserContext,
    Page, Playwright,
)
from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) "
    "Gecko/20100101 Firefox/133.0",
]

VIEWPORTS = [
    {"width": 1366, "height": 768},
    {"width": 1440, "height": 900},
    {"width": 1920, "height": 1080},
    {"width": 1280, "height": 800},
]

# Stealth JS — removes all webdriver fingerprints
_STEALTH_JS = """
// Remove webdriver flag
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});

// Fake plugins
Object.defineProperty(navigator, 'plugins', {
    get: () => [
        {name:'Chrome PDF Plugin', filename:'internal-pdf-viewer', description:'Portable Document Format', length:1},
        {name:'Chrome PDF Viewer', filename:'mhjfbmdgcfjbbpaeojofohoefgiehjai', description:'', length:1},
        {name:'Native Client', filename:'internal-nacl-plugin', description:'', length:2}
    ]
});

// Real languages for India
Object.defineProperty(navigator, 'languages', {get: () => ['en-IN','en-US','en','hi']});

// Hardware
Object.defineProperty(navigator, 'hardwareConcurrency', {get: () => 8});
Object.defineProperty(navigator, 'deviceMemory', {get: () => 8});

// Chrome object
window.chrome = {
    app: {isInstalled: false, InstallState: {DISABLED:'d',INSTALLED:'i',NOT_INSTALLED:'n'}, RunningState: {CANNOT_RUN:'c',READY_TO_RUN:'r',RUNNING:'ru'}},
    runtime: {OnInstalledReason: {CHROME_UPDATE:'chrome_update',INSTALL:'install',SHARED_MODULE_UPDATE:'shared_module_update',UPDATE:'update'}, OnRestartRequiredReason: {APP_UPDATE:'app_update',OS_UPDATE:'os_update',PERIODIC:'periodic'}, PlatformArch: {ARM:'arm', X86_32:'x86-32', X86_64:'x86-64'}, PlatformNaclArch: {ARM:'arm', X86_32:'x86-32', X86_64:'x86-64'}, PlatformOs: {ANDROID:'android',CROS:'cros',LINUX:'linux',MAC:'mac',OPENBSD:'openbsd',WIN:'win'}, RequestUpdateCheckStatus: {NO_UPDATE:'no_update',THROTTLED:'throttled',UPDATE_AVAILABLE:'update_available'}},
    loadTimes: function() {},
    csi: function() {},
};

// Permissions
const origQuery = window.navigator.permissions.query;
window.navigator.permissions.query = (p) =>
    p.name === 'notifications'
        ? Promise.resolve({state: Notification.permission})
        : origQuery(p);

// WebGL vendor
const getParam = WebGLRenderingContext.prototype.getParameter;
WebGLRenderingContext.prototype.getParameter = function(p) {
    if (p === 37445) return 'Intel Inc.';
    if (p === 37446) return 'Intel Iris OpenGL Engine';
    return getParam.call(this, p);
};

// Screen
Object.defineProperty(screen, 'colorDepth', {get: () => 24});
Object.defineProperty(screen, 'pixelDepth',  {get: () => 24});
"""


class PlaywrightManager:
    _instance:   Optional["PlaywrightManager"] = None
    _playwright: Optional[Playwright]           = None
    _browser:    Optional[Browser]              = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance           = super().__new__(cls)
            cls._instance._contexts = {}
        return cls._instance

    async def start(self):
        if self._browser:
            return
        self._playwright = await async_playwright().start()
        self._browser    = await self._playwright.chromium.launch(
            headless=settings.playwright_headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-features=IsolateOrigins,site-per-process",
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-accelerated-2d-canvas",
                "--no-first-run",
                "--no-zygote",
                "--disable-gpu",
                "--window-size=1366,768",
                "--disable-notifications",
                "--disable-background-timer-throttling",
                "--disable-popup-blocking",
            ],
        )
        logger.info(
            "Playwright started (headless=%s)", settings.playwright_headless
        )

    async def stop(self):
        for ctx in getattr(self, "_contexts", {}).values():
            try:
                await ctx.close()
            except Exception:
                pass
        self._contexts = {}
        if self._browser:
            try:
                await self._browser.close()
            except Exception:
                pass
            self._browser = None
        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception:
                pass
            self._playwright = None
        logger.info("Playwright stopped")

    async def _get_context(self, domain: str) -> BrowserContext:
        # Each domain gets its OWN context (separate cookies, fingerprint)
        if domain not in self._contexts:
            ctx = await self._browser.new_context(
                viewport=random.choice(VIEWPORTS),
                user_agent=random.choice(USER_AGENTS),
                locale="en-IN",
                timezone_id="Asia/Kolkata",
                java_script_enabled=True,
                accept_downloads=False,
                extra_http_headers={
                    "Accept": (
                        "text/html,application/xhtml+xml,"
                        "application/xml;q=0.9,image/avif,"
                        "image/webp,image/apng,*/*;q=0.8"
                    ),
                    "Accept-Language":  "en-IN,en-US;q=0.9,en;q=0.8",
                    "Accept-Encoding":  "gzip, deflate, br",
                    "Connection":       "keep-alive",
                    "Upgrade-Insecure-Requests": "1",
                    "Sec-Fetch-Dest":   "document",
                    "Sec-Fetch-Mode":   "navigate",
                    "Sec-Fetch-Site":   "none",
                    "Sec-Fetch-User":   "?1",
                },
            )
            # Apply stealth JS to every new page in this context
            await ctx.add_init_script(_STEALTH_JS)

            # Block ads/trackers to speed up loading
            await ctx.route(
                "**/(googlesyndication|doubleclick|analytics|tracking|"
                "google-analytics|googletagmanager|facebook|twitter|"
                "hotjar|clarity|segment).**",
                lambda route: route.abort(),
            )
            self._contexts[domain] = ctx
            logger.debug("New browser context for domain: %s", domain)

        return self._contexts[domain]

    async def new_page(self, domain: str = "default") -> Page:
        if not self._browser:
            await self.start()
        ctx  = await self._get_context(domain)
        page = await ctx.new_page()
        page.set_default_timeout(20000)

        # Apply playwright-stealth if installed
        try:
            from playwright_stealth import stealth_async
            await stealth_async(page)
        except ImportError:
            pass  # Falls back to init script above

        return page

    async def random_delay(self, min_ms: int = 500, max_ms: int = 1200):
        delay = random.uniform(min_ms / 1000.0, max_ms / 1000.0)
        await asyncio.sleep(delay)

    async def reset_context(self, domain: str):
        """Force a fresh context for a domain (call after bot challenge)."""
        if domain in self._contexts:
            try:
                await self._contexts[domain].close()
            except Exception:
                pass
            del self._contexts[domain]
            logger.info("Reset browser context for: %s", domain)


playwright_manager = PlaywrightManager()
