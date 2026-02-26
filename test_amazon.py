"""Quick test with Amazon to verify price extraction."""
import requests
import json

body = {
    "query": "Samsung Galaxy S24 128GB",
    "preferences": {"mode": "balanced", "min_match_score": 0.25},
    "allowed_marketplaces": ["amazon"]
}

print(f"Testing: {body['query']} on {body['allowed_marketplaces']}")
print("-" * 60)

try:
    r = requests.post(
        "http://127.0.0.1:8000/api/debug/compare",
        json=body,
        timeout=120,
    )
    data = r.json()

    with open("test_amazon.json", "w") as f:
        json.dump(data, f, indent=2, default=str)

    print(f"Status: {r.status_code}")
    print(f"Query time: {data.get('query_time_seconds')}s")
    print(f"Counts: {data.get('counts')}")
    print(f"Errors: {data.get('errors')}")
    print()

    for s in data.get("site_statuses", []):
        print(f"  [{s['marketplace_key']}] {s['status']} - {s['message']}")
    print()

    raw = data.get("raw_listings", [])
    print(f"Raw listings: {len(raw)}")
    for i, r_item in enumerate(raw[:3]):
        print(f"  [{i}] title: {r_item.get('title','')[:60]}")
        print(f"       price_text: {r_item.get('price_text')}")
        print(f"       url: {r_item.get('listing_url','')[:80]}")
    print()

    final = data.get("final_offers", [])
    print(f"Final offers: {len(final)}")
    for i, o in enumerate(final[:5]):
        print(f"  [{i+1}] {o.get('platform_name','?')}: {o.get('title','')[:50]}")
        print(f"       price={o.get('effective_price')} badges={o.get('badges',[])}")
    print()
    print(f"Explanation: {data.get('explanation', '')[:200]}")
    print("Full result saved to test_amazon.json")

except Exception as e:
    print(f"ERROR: {e}")
