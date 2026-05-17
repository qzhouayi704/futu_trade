import sqlite3
c = sqlite3.connect(r"D:\Program Files\futu_trade_sys\simple_trade\data\trade.db")
rows = c.execute("SELECT code,name FROM stocks WHERE code IN ('HK.02635','HK.02587','HK.01072')").fetchall()
with open(r"D:\Program Files\futu_trade_sys\simple_trade\scripts\_names.txt", "w", encoding="utf-8") as f:
    for r in rows:
        f.write(f"{r[0]} {r[1]}\n")
c.close()
print("done")
