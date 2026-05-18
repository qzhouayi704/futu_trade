import json, sys
sys.stdout.reconfigure(encoding='utf-8')

data = json.load(open(r"d:\Program Files\futu_trade_sys\overnight_export.json", encoding="utf-8"))

for i, entry in enumerate(data):
    screen_date = entry.get("screen_date", "unknown")
    candidates = json.loads(entry["candidates_json"])
    print(f"\n=== {screen_date} ({len(candidates)} candidates) ===")
    for c in candidates[:15]:
        code = c["stock_code"]
        score = c["total_score"]
        cat = c.get("category", "N/A")
        verdict = c.get("verdict", "")
        print(f"  {code:12s} score={score:5.1f}  cat={cat:10s}  verdict={verdict}")
