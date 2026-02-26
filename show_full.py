"""Show full test stats - safe encoding."""
import json, sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
d = json.load(open("test_full.json", encoding="utf-8"))
print(f"TIME: {d.get('query_time_seconds')}s")
c = d.get("counts", {})
print(f"RAW={c.get('raw_listings',0)} NORM={c.get('normalized_offers',0)} MATCH={c.get('matched_offers',0)} FINAL={c.get('final_offers',0)}")
print()
for s in d.get("site_statuses", []):
    st = s['status']
    nm = s['marketplace_key']
    ln = s.get('listings_found', 0)
    ms = s.get('message','').encode('ascii','replace').decode('ascii')[:60]
    print(f"  {nm:22s} {st:14s} {ln} listings | {ms}")
print()
for e in d.get("errors", []):
    print(f"  ERR: {e[:80]}")
print()
for i, o in enumerate(d.get("final_offers", [])[:10]):
    p = o.get('effective_price')
    ps = f"Rs.{p:,.0f}" if p else "null"
    t = o.get('title','').encode('ascii','replace').decode('ascii')[:55]
    print(f"  #{i+1} [{o.get('platform_key','')}] {t} | {ps} | match={o.get('match_score',0):.2f} | badges={o.get('badges',[])}")
exp = d.get("explanation","")
if exp:
    print(f"\nEXPL: {exp.encode('ascii','replace').decode('ascii')[:250]}")
