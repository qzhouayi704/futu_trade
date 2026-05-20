import urllib.request, json

BASE = "http://170.106.152.108:9090/api"
CODE = "HK.02523"

# 1. 资金流时间线
try:
    r1 = urllib.request.urlopen(f"{BASE}/enhanced-heat/capital-flow-timeline/{CODE}", timeout=15)
    flow = json.loads(r1.read())
    pts = flow.get("data", [])
    msg = flow.get("message", "")
    print(f"flow timeline: {len(pts)} pts, msg={msg}")
    for p in pts[-5:]:
        print(f"  {p}")
except Exception as e:
    print(f"flow timeline error: {e}")

# 2. 分时数据
try:
    r2 = urllib.request.urlopen(f"{BASE}/enhanced-heat/intraday-timeline/{CODE}", timeout=15)
    rt = json.loads(r2.read())
    rpts = rt.get("data", [])
    print(f"\nrt timeline: {len(rpts)} pts")
    if rpts:
        for p in rpts[-5:]:
            t = p.get("time", "")
            pr = p.get("price", 0)
            vol = p.get("volume", 0)
            print(f"  {t} price={pr} vol={vol}")
except Exception as e:
    print(f"rt timeline error: {e}")

# 3. 支撑阻力
try:
    r3 = urllib.request.urlopen(f"{BASE}/enhanced-heat/intraday-levels/{CODE}", timeout=15)
    lv = json.loads(r3.read())
    ld = lv.get("data", {})
    if ld:
        print(f"\ncurrent_price: {ld.get('current_price')}")
        vwap = ld.get("vwap")
        if vwap:
            print(f"VWAP: {vwap.get('price')} ({vwap.get('deviation_pct'):+.2f}%)")
        for r in ld.get("resistance_levels", []):
            print(f"  resistance: {r['price']} str={r['strength']} {r.get('label','')}")
        for s in ld.get("support_levels", []):
            print(f"  support: {s['price']} str={s['strength']} {s.get('label','')}")
    else:
        print(f"\nlevels: {lv.get('message','no data')}")
except Exception as e:
    print(f"levels error: {e}")
