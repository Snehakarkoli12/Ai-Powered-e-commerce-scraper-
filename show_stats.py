"""Show just the key stats from stealth test."""
import json, sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
d = json.load(open("test_stealth.json", encoding="utf-8"))
print(f"TIME: {d.get('query_time_seconds')}s")
print(f"COUNTS: {json.dumps(d.get('counts', {}))}")
print(f"ERRORS: {d.get('errors')}")
print()
for s in d.get("site_statuses", []):
    print(f"SITE: {s['marketplace_key']} = {s['status']} ({s.get('listings_found',0)} listings)")
    print(f"  MSG: {s.get('message','')[:80]}")
print()
for i, o in enumerate(d.get("final_offers", [])):
    p = o.get('effective_price')
    pstr = f"Rs.{p:,.0f}" if p else "null"
    t = o.get('title','')[:55]
    m = o.get('match_score', 0)
    b = o.get('badges', [])
    print(f"OFFER {i+1}: [{o.get('platform_key','')}] {t}")
    print(f"  price={pstr} | match={m} | badges={b}")
