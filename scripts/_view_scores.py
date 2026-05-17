import json
d = json.load(open('scripts/scoring_backtest.json','r',encoding='utf-8'))

print('=== 80-100 trades (high score) ===')
for t in d['scored_trades']:
    if t['score'] >= 80:
        print(f"  {t['result']:4s} {t['actual_pct']:+6.2f}% | score={t['score']} | {t['code']} {t['date']} hold={t['hold_minutes']}min")
        for k,v in t['details'].items():
            val = v.get('value','?')
            print(f"    {k}: {val} -> {v['score']}/{v['max']}")
        print()

print('=== 60-79 WIN examples ===')
cnt=0
for t in d['scored_trades']:
    if 60 <= t['score'] < 80 and t['result']=='WIN' and cnt<3:
        print(f"  {t['result']:4s} {t['actual_pct']:+6.2f}% | score={t['score']} | {t['code']} {t['date']}")
        cnt+=1

print()
print('=== <30 LOSS examples ===')
cnt=0
for t in d['scored_trades']:
    if t['score'] < 30 and t['result']=='LOSS' and cnt<5:
        print(f"  {t['result']:4s} {t['actual_pct']:+6.2f}% | score={t['score']} | {t['code']} {t['date']}")
        for k,v in t['details'].items():
            val = v.get('value','?')
            print(f"    {k}: {val} -> {v['score']}/{v['max']}")
        print()
        cnt+=1
