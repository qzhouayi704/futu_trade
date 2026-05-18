import sqlite3, json

DB = "/opt/futu_trade_sys/simple_trade/data/trade.db"
conn = sqlite3.connect(DB)
cur = conn.cursor()

targets = ['HK.02565', 'HK.06651', 'HK.02661', 'HK.02701']

# 1. Check plates/sectors for each stock
print("=== 爆发股板块归属 ===")
for code in targets:
    cur.execute("SELECT name FROM stocks WHERE code = ?", (code,))
    nr = cur.fetchone()
    name = nr[0] if nr else code
    
    # Check stock_plates table
    cur.execute("""
        SELECT p.name, p.plate_type 
        FROM stock_plates sp 
        JOIN plates p ON sp.plate_code = p.code 
        WHERE sp.stock_code = ?
    """, (code,))
    plates = cur.fetchall()
    
    print(f"\n{code} {name}:")
    if plates:
        for p_name, p_type in plates:
            print(f"  [{p_type}] {p_name}")
    else:
        print("  无板块数据")

# 2. Find common plates
print("\n\n=== 共同板块 ===")
plate_sets = {}
for code in targets:
    cur.execute("""
        SELECT p.name FROM stock_plates sp 
        JOIN plates p ON sp.plate_code = p.code 
        WHERE sp.stock_code = ?
    """, (code,))
    plate_sets[code] = set(r[0] for r in cur.fetchall())

# Find intersections
if all(plate_sets.values()):
    common = set.intersection(*plate_sets.values())
    if common:
        print(f"4只股共同板块: {common}")
    else:
        print("无完全共同板块")
    
    # Pairwise overlaps
    codes = list(plate_sets.keys())
    for i in range(len(codes)):
        for j in range(i+1, len(codes)):
            overlap = plate_sets[codes[i]] & plate_sets[codes[j]]
            if overlap:
                print(f"  {codes[i]} ∩ {codes[j]}: {overlap}")

# 3. Check today's hot plates
print("\n\n=== 今日热门板块(按涨幅) ===")
cur.execute("""
    SELECT p.name, p.change_rate, p.plate_type
    FROM plates p
    WHERE p.change_rate IS NOT NULL
    ORDER BY p.change_rate DESC
    LIMIT 15
""")
hot = cur.fetchall()
for p_name, chg, pt in hot:
    print(f"  {p_name:20s} {chg:+.2f}%  [{pt}]")

conn.close()
