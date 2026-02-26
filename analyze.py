"""Analyze test_result.json"""
import json

with open("test_result.json") as f:
    d = json.load(f)

print("=== PIPELINE RESULTS ===")
print(f"Query time: {d.get('query_time_seconds')}s")
print(f"Counts: {d.get('counts')}")
print(f"Errors: {d.get('errors')}")
print()

print("=== SITE STATUSES ===")
for s in d.get("site_statuses", []):
    print(f"  [{s['marketplace_key']}] {s['status']} - {s['message']}")
print()

print("=== RAW LISTINGS ===")
raw = d.get("raw_listings", [])
print(f"Total: {len(raw)}")
for i, r in enumerate(raw[:5]):
    print(f"  [{i}] title: {r.get('title','')[:60]}")
    print(f"       price_text: {r.get('price_text')}")
    print(f"       listing_url: {r.get('listing_url','')[:80]}")
    print(f"       rating: {r.get('rating_text')}")
print()

print("=== FINAL OFFERS ===")
final = d.get("final_offers", [])
print(f"Total: {len(final)}")
for i, o in enumerate(final[:5]):
    print(f"  [{i+1}] {o.get('platform_name','?')} - {o.get('title','')[:50]}")
    print(f"       effective_price: {o.get('effective_price')}")
    print(f"       match_score: {o.get('match_score')}")
    print(f"       badges: {o.get('badges', [])}")
    sb = o.get("score_breakdown", {})
    print(f"       scores: price={sb.get('price_score')}, delivery={sb.get('delivery_score')}, trust={sb.get('trust_score')}, final={sb.get('final_score')}")
print()

print(f"Explanation: {d.get('explanation', '')[:200]}")
