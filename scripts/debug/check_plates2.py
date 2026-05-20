import sqlite3

DB = "/opt/futu_trade_sys/simple_trade/data/trade.db"
conn = sqlite3.connect(DB)
cur = conn.cursor()

targets = ['HK.02565', 'HK.06651', 'HK.02661', 'HK.02701']

# Use stock_plates (stock_id -> plate_id)
print("=== 爆发股板块归属 ===")
plate_map = {}
for code in targets:
    cur.execute("SELECT id, name FROM stocks WHERE code = ?", (code,))
    sr = cur.fetchone()
    if not sr:
        print(f"{code}: 无stocks记录")
        continue
    stock_id, name = sr
    
    cur.execute("""
        SELECT p.plate_name, p.category 
        FROM stock_plates sp 
        JOIN plates p ON sp.plate_id = p.id 
        WHERE sp.stock_id = ?
    """, (stock_id,))
    plates = cur.fetchall()
    
    plate_names = set()
    print(f"\n{code} {name}:")
    if plates:
        for pn, pc in plates:
            print(f"  [{pc or ''}] {pn}")
            plate_names.add(pn)
    else:
        print("  无板块关联")
    plate_map[code] = plate_names

# Common plates
print("\n=== 板块交集 ===")
codes = list(plate_map.keys())
for i in range(len(codes)):
    for j in range(i+1, len(codes)):
        overlap = plate_map[codes[i]] & plate_map[codes[j]]
        if overlap:
            print(f"  {codes[i]} ∩ {codes[j]}: {overlap}")

# All plates count
all_plates = {}
for code, ps in plate_map.items():
    for p in ps:
        all_plates[p] = all_plates.get(p, [])
        all_plates[p].append(code)

print("\n=== 板块出现频次 ===")
for p, codes_list in sorted(all_plates.items(), key=lambda x: len(x[1]), reverse=True):
    if len(codes_list) >= 2:
        print(f"  {p}: {len(codes_list)}只 → {codes_list}")

conn.close()
