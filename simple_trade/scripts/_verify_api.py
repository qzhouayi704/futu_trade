import urllib.request, json
r = urllib.request.urlopen('http://170.106.152.108:9090/api/enhanced-heat/capital-flow-timeline/HK.02172', timeout=10)
d = json.loads(r.read())
pts = d.get('data', [])
msg = d.get('message', '')
print(f"message: {msg}")
print(f"data points: {len(pts)}")
if pts:
    for p in pts[:5]:
        print(f"  {p['time']}")
    print("  ...")
    for p in pts[-3:]:
        print(f"  {p['time']}")
else:
    print("  empty - OK (no trading data yet)")
