"""Diagnose each site: test URLs, check what Playwright actually fetches."""
import asyncio
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.marketplaces.registry import marketplace_registry
from urllib.parse import quote_plus


async def diagnose():
    from playwright.async_api import async_playwright

    query = "Samsung Galaxy S24"
    configs = marketplace_registry.get_all_enabled()

    print(f"Testing {len(configs)} marketplaces with query: '{query}'")
    print("=" * 80)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)

        for cfg in configs:
            url = cfg.search_url_pattern.format(query=quote_plus(query))
            print(f"\n--- {cfg.name} ({cfg.key}) ---")
            print(f"URL: {url[:100]}")

            try:
                ctx = await browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/122.0.0.0 Safari/537.36"
                    ),
                    viewport={"width": 1280, "height": 800},
                    locale="en-IN",
                )
                page = await ctx.new_page()

                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=20000)
                    await asyncio.sleep(3)

                    # Get page title and text length
                    title = await page.title()
                    text = await page.evaluate("() => document.body ? document.body.innerText : ''")
                    html_len = await page.evaluate("() => document.documentElement.outerHTML.length")

                    # Check for bot detection
                    bot_phrases = cfg.bot_detection_phrases or []
                    text_lower = text.lower()
                    bot_detected = None
                    for phrase in bot_phrases:
                        if phrase.lower() in text_lower:
                            bot_detected = phrase
                            break

                    # Check for price-like patterns in text
                    import re
                    prices = re.findall(r'(?:Rs\.?|INR)\s*[\d,]+', text)
                    price_nums = re.findall(r'[\d,]{4,}', text)  # 4+ digit numbers

                    print(f"  Title: {title[:60]}")
                    print(f"  Text length: {len(text)} chars | HTML: {html_len} chars")
                    print(f"  Bot detected: {bot_detected or 'NO'}")
                    print(f"  Price patterns found: {len(prices)} (Rs/INR format)")
                    print(f"  Text preview: {text[:200].replace(chr(10), ' ')}")

                    # Save snapshot for analysis
                    snap_path = f"app/scraping/debug/diag_{cfg.key}.html"
                    html = await page.content()
                    with open(snap_path, "w", encoding="utf-8") as f:
                        f.write(html)
                    print(f"  Snapshot saved: {snap_path}")

                except Exception as e:
                    print(f"  ERROR: {str(e)[:100]}")

                await ctx.close()

            except Exception as e:
                print(f"  CONTEXT ERROR: {str(e)[:100]}")

        await browser.close()

    print("\n" + "=" * 80)
    print("DIAGNOSIS COMPLETE")


if __name__ == "__main__":
    asyncio.run(diagnose())
