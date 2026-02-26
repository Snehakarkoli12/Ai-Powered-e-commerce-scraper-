"""Full multi-site test with all 10 marketplaces."""
import requests
import json
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

body = {
    "query": "Samsung Galaxy S24 128GB",
    "preferences": {"mode": "balanced", "min_match_score": 0.25},
}

print(f"FULL TEST: {body['query']} (ALL sites)")
print("=" * 60)

try:
    r = requests.post(
        "http://127.0.0.1:8000/api/compare",
        json=body,
        timeout=300,
    )
    data = r.json()

    with open("test_full.json", "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str, ensure_ascii=True)

    print(f"TIME: {data.get('query_time_seconds')}s")
    counts = data.get("counts", {})
    print(f"RAW: {counts.get('raw_listings', 0)} | NORMALIZED: {counts.get('normalized_offers', 0)} | "
          f"MATCHED: {counts.get('matched_offers', 0)} | FINAL: {counts.get('final_offers', 0)}")
    print()

    print("SITE STATUSES:")
    for s in data.get("site_statuses", []):
        status_emoji = {
            "ok": "OK", "error": "ERR", "timeout": "TMO",
            "bot_challenge": "BOT", "no_results": "NIL", "pending": "..."
        }.get(s["status"], "???")
        print(f"  [{status_emoji}] {s['marketplace_key']:20s} | {s.get('listings_found',0)} listings | {s.get('message','')[:60]}")
    print()

    errors = data.get("errors", [])
    if errors:
        print(f"ERRORS ({len(errors)}):")
        for e in errors:
            print(f"  - {e[:80]}")
        print()

    print("FINAL OFFERS:")
    for i, o in enumerate(data.get("final_offers", [])):
        p = o.get('effective_price')
        pstr = f"Rs.{p:,.0f}" if p else "null"
        t = o.get('title', '')[:55]
        m = o.get('match_score', 0)
        b = o.get('badges', [])
        sb = o.get('score_breakdown', {})
        print(f"  #{i+1} [{o.get('platform_key','')}] {t}")
        print(f"     price={pstr} | match={m:.2f} | final={sb.get('final_score',0):.3f} | badges={b}")
    print()

    exp = data.get("explanation", "")
    if exp:
        print(f"AI RECOMMENDATION: {exp[:300]}")

    print(f"\nFull JSON saved to test_full.json")

except Exception as e:
    print(f"ERROR: {e}")
