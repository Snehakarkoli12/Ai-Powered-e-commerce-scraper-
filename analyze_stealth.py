"""Analyze stealth test - handle unicode."""
import json, os, sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

for fname in ["test_stealth.json"]:
    if not os.path.exists(fname):
        print(f"Missing: {fname}")
        continue
    with open(fname, encoding="utf-8") as f:
        d = json.load(f)
    print(f"Time: {d.get('query_time_seconds')}s")
    print(f"Counts: {d.get('counts')}")
    print(f"Errors: {d.get('errors')}")
    for s in d.get("site_statuses", []):
        msg = s.get('message','')
        # Sanitize non-ascii
        msg = msg.encode('ascii', 'replace').decode('ascii')
        print(f"  {s['marketplace_key']}: {s['status']} | {msg[:80]}")
    raw = d.get("raw_listings", [])
    print(f"Raw: {len(raw)}")
    for i, r in enumerate(raw[:5]):
        t = r.get('title','').encode('ascii','replace').decode('ascii')[:60]
        p = str(r.get('price_text','')).encode('ascii','replace').decode('ascii')
        u = str(r.get('listing_url','')).encode('ascii','replace').decode('ascii')[:60]
        print(f"  [{i}] {t} | price={p} | url={u}")
    final = d.get("final_offers", [])
    print(f"Final: {len(final)}")
    for i, o in enumerate(final[:5]):
        t = o.get('title','').encode('ascii','replace').decode('ascii')[:50]
        print(f"  [{i+1}] {o.get('platform_name','?')}: {t}")
        print(f"       eff_price={o.get('effective_price')} match={o.get('match_score')} badges={o.get('badges')}")
    exp = d.get('explanation','')
    if exp:
        print(f"Explanation: {exp.encode('ascii','replace').decode('ascii')[:200]}")
