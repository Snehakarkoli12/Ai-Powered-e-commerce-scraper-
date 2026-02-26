"""Test stealth scraper with 2 sites to verify anti-detection works."""
import requests
import json

# Test with 2 sites that were previously blocked
body = {
    "query": "Samsung Galaxy S24 128GB",
    "preferences": {"mode": "balanced", "min_match_score": 0.25},
    "allowed_marketplaces": ["amazon", "flipkart"]
}

print(f"Testing: {body['query']}")
print(f"Sites: {body['allowed_marketplaces']}")
print("-" * 60)

try:
    r = requests.post(
        "http://127.0.0.1:8000/api/debug/compare",
        json=body,
        timeout=180,
    )
    data = r.json()

    with open("test_stealth.json", "w") as f:
        json.dump(data, f, indent=2, default=str)

    print(f"Status: {r.status_code}")
    print(f"Time: {data.get('query_time_seconds')}s")
    print(f"Counts: {data.get('counts')}")
    print(f"Errors: {data.get('errors')}")
    print()

    for s in data.get("site_statuses", []):
        print(f"  [{s['marketplace_key']}] {s['status']} - {s['message']}")
    print()

    raw = data.get("raw_listings", [])
    print(f"Raw listings: {len(raw)}")
    for i, r_item in enumerate(raw[:5]):
        print(f"  [{i}] {r_item.get('title','')[:60]}")
        print(f"       price={r_item.get('price_text')} | url={r_item.get('listing_url','')[:60]}")
    print()

    final = data.get("final_offers", [])
    print(f"Final offers: {len(final)}")
    for i, o in enumerate(final[:5]):
        print(f"  [{i+1}] {o.get('platform_name','?')}: {o.get('title','')[:50]}")
        print(f"       price={o.get('effective_price')} | match={o.get('match_score')} | badges={o.get('badges')}")

except Exception as e:
    print(f"ERROR: {e}")
