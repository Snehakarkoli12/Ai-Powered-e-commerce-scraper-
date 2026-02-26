"""Analyze Amazon test result"""
import json, os

for fname in ["test_amazon.json", "test_result.json"]:
    if os.path.exists(fname):
        with open(fname) as f:
            d = json.load(f)
        print(f"=== {fname} ===")
        print(f"Time: {d.get('query_time_seconds')}s")
        print(f"Counts: {d.get('counts')}")
        print(f"Errors: {d.get('errors')}")
        for s in d.get("site_statuses", []):
            print(f"  Site: {s['marketplace_key']} | status={s['status']} | msg={s['message'][:80]}")
        raw = d.get("raw_listings", [])
        print(f"Raw: {len(raw)}")
        for r in raw[:3]:
            print(f"  title={r.get('title','')[:50]} | price={r.get('price_text')} | url={r.get('listing_url','')[:60]}")
        final = d.get("final_offers", [])
        print(f"Final: {len(final)}")
        for o in final[:3]:
            print(f"  {o.get('title','')[:50]} | price={o.get('effective_price')} | badges={o.get('badges')}")
        print(f"Explanation: {d.get('explanation','')[:150]}")
        print()
