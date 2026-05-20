import urllib.request, json

BASE = "http://170.106.152.108:9090/api"
CODE = "HK.01384"

# 1. 资金流时间线
try:
    r1 = urllib.request.urlopen(f"{BASE}/enhanced-heat/capital-flow-timeline/{CODE}", timeout=15)
    flow = json.loads(r1.read())
    pts = flow.get("data", [])
    msg = flow.get("message", "")
    print(f"=== {CODE} capital flow ({len(pts)} pts) | {msg} ===")
    print(f"{'time':>6} {'net_buy':>8} {'cum_net':>8} {'price':>8}")
    print("-" * 38)
    for p in pts:
        t = p.get("time", "")
        nb = p.get("net_buy", 0)
        cn = p.get("cum_net", 0)
        pr = p.get("price", 0)
        pr_s = f"{pr:.3f}" if pr else "   -"
        print(f"{t:>6} {nb:>8.1f} {cn:>8.1f} {pr_s:>8}")

    if pts:
        last = pts[-1]
        first = pts[0]
        cum = last.get("cum_net", 0)
        total_buy = sum(p.get("buy_in", 0) for p in pts)
        total_sell = sum(abs(p.get("sell_in", 0)) for p in pts)
        print(f"\n--- Summary ---")
        print(f"cum_net: {cum:.1f} wan")
        print(f"total_buy: {total_buy:.1f} wan")
        print(f"total_sell: {total_sell:.1f} wan")
        if total_sell > 0:
            print(f"buy/sell ratio: {total_buy/total_sell:.2f}")
        # Trend analysis
        mid = len(pts) // 2
        first_half_net = sum(p.get("net_buy", 0) for p in pts[:mid])
        second_half_net = sum(p.get("net_buy", 0) for p in pts[mid:])
        print(f"first half net: {first_half_net:.1f}")
        print(f"second half net: {second_half_net:.1f}")
except Exception as e:
    print(f"flow error: {e}")

# 2. 支撑阻力
try:
    r3 = urllib.request.urlopen(f"{BASE}/enhanced-heat/intraday-levels/{CODE}", timeout=15)
    lv = json.loads(r3.read())
    ld = lv.get("data", {})
    if ld:
        print(f"\n=== Levels ===")
        print(f"current: {ld.get('current_price')}")
        vwap = ld.get("vwap")
        if vwap:
            print(f"VWAP: {vwap.get('price')} ({vwap.get('deviation_pct'):+.2f}%)")
        poc = ld.get("poc")
        if poc:
            print(f"POC: {poc.get('price')} vol={poc.get('volume')}")
        for r in sorted(ld.get("resistance_levels", []), key=lambda x: x["price"], reverse=True):
            print(f"  R: {r['price']:.3f} str={r['strength']} {r.get('label','')}")
        for s in sorted(ld.get("support_levels", []), key=lambda x: x["price"], reverse=True):
            print(f"  S: {s['price']:.3f} str={s['strength']} {s.get('label','')}")
    else:
        print(f"\nlevels: {lv.get('message','no data')}")
except Exception as e:
    print(f"levels error: {e}")
