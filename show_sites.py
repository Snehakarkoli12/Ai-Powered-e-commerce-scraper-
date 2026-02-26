"""Per-site summary only."""
import json, sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
d = json.load(open("test_full.json", encoding="utf-8"))

# Group final offers by platform
from collections import Counter
final = d.get("final_offers", [])
pcount = Counter(o.get("platform_key","?") for o in final)

print("SITE STATUSES:")
for s in d.get("site_statuses", []):
    nm = s['marketplace_key']
    st = s['status']
    ln = s.get('listings_found', 0)
    fn = pcount.get(nm, 0)
    ms = s.get('message','').encode('ascii','replace').decode('ascii')[:50]
    print(f"  {nm:22s} status={st:14s} raw={ln} final={fn} | {ms}")

print(f"\nTOTAL: {len(final)} final offers across {len(pcount)} sites")
print(f"Sites with data: {dict(pcount)}")

# Show all offers briefly
print(f"\nALL {len(final)} OFFERS:")
for i, o in enumerate(final):
    p = o.get('effective_price')
    ps = f"Rs.{p:,.0f}" if p else "null"
    t = o.get('title','').encode('ascii','replace').decode('ascii')[:40]
    print(f"  #{i+1} [{o.get('platform_key','')}] {ps:>12s} | {t}")
