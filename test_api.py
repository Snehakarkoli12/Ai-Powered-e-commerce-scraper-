"""Quick test script — run a single-site scrape to verify price extraction."""
import requests
import json
import sys

body = {
    "query": "JBL Tune 770NC Wireless Headphones",
    "preferences": {"mode": "balanced", "min_match_score": 0.25},
    "allowed_marketplaces": ["vijay_sales"]
}

print(f"Testing: POST /api/debug/compare with site=vijay_sales")
print(f"Query: {body['query']}")
print("-" * 60)

try:
    r = requests.post(
        "http://127.0.0.1:8000/api/debug/compare",
        json=body,
        timeout=120,
    )
    data = r.json()

    # Save full result
    with open("test_result.json", "w") as f:
        json.dump(data, f, indent=2, default=str)

    print(f"Status: {r.status_code}")
    print(f"Query time: {data.get('query_time_seconds', '?')}s")
    print(f"Product: {data.get('normalized_product', {})}")
    print(f"Counts: {data.get('counts', {})}")
    print(f"Errors: {data.get('errors', [])}")
    print()

    # Check site statuses
    for s in data.get("site_statuses", []):
        if isinstance(s, dict):
            print(f"  [{s.get('marketplace_key')}] {s.get('status')} — {s.get('message')}")
        else:
            print(f"  {s}")

    print()

    # Check raw listings
    raw = data.get("raw_listings", [])
    print(f"Raw listings: {len(raw)}")
    for i, item in enumerate(raw[:3]):
        if isinstance(item, dict):
            print(f"  [{i}] title={item.get('title','')[:60]}")
            print(f"       price_text={item.get('price_text')}")
            print(f"       listing_url={item.get('listing_url','')[:80]}")
        else:
            print(f"  [{i}] {item}")

    print()

    # Check final offers
    final = data.get("final_offers", [])
    print(f"Final offers: {len(final)}")
    for i, offer in enumerate(final[:5]):
        if isinstance(offer, dict):
            print(f"  [{i+1}] {offer.get('platform_name','?')} — {offer.get('title','')[:50]}")
            print(f"       price={offer.get('effective_price')} | match={offer.get('match_score')}")
            print(f"       badges={offer.get('badges', [])}")
            print(f"       url={offer.get('listing_url','')[:80]}")
        else:
            print(f"  [{i+1}] {offer}")

    print()
    print(f"Explanation: {data.get('explanation', '')[:200]}")
    print()
    print("Full result saved to test_result.json")

except Exception as e:
    print(f"ERROR: {e}")
    sys.exit(1)
