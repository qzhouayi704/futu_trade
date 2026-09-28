"""Normalize archived data without repairing absent minute observations."""
from collections import Counter, defaultdict
from datetime import date
import gzip
import hashlib
import json
from pathlib import Path
import numpy as np

from scripts.analysis.minute_entry_study.models import Event, INDEX, N, Tape, build_features, stamp, wall_minute
from .models import Background, Daily, Market, Opportunity, StockPath


def theme_of(sector: str) -> str | None:
    if '人工智能' in sector or 'AI' in sector.upper():
        return 'AI'
    if '芯片' in sector or '半导体' in sector:
        return '芯片'
    if any(word in sector for word in ('医药','医疗','生物','创新药')):
        return '医药'
    if '光伏' in sector:
        return '光伏'
    if any(word in sector for word in ('科技','科网','软件','机器人','智能驾驶','互联网设施')):
        return '科技'
    return None


def background(rows: list[Daily], day: str) -> Background:
    previous = [row for row in rows if row.day < day][-21:]
    good = (len(previous) >= 21 and not any(row.conflict for row in previous)
            and (date.fromisoformat(day)-date.fromisoformat(previous[-1].day)).days <= 5)
    if not good:
        return Background(False,.03,0,0,0,0,0,0,0,False)
    recent = previous[-20:]
    tr = [max(current.high-current.low,abs(current.high-prior.close),abs(current.low-prior.close))
          for prior,current in zip(previous,previous[1:])]
    atr = float(np.mean(tr[-14:]))/previous[-1].close
    return Background(True,atr,min(r.low for r in recent),max(r.high for r in recent),
                      float(np.mean([r.close for r in recent[-5:]])),float(np.mean([r.close for r in recent])),
                      min(r.low for r in recent[-5:]),previous[-1].close,
                      float(np.mean([r.turnover for r in recent])),
                      previous[-1].close >= previous[-2].close and
                      min(r.low for r in recent[-3:]) >= min(r.low for r in recent[-6:-3])*.99)


def load(path: Path) -> Market:
    raw = path.read_bytes()
    data = json.loads(gzip.decompress(raw))
    days = sorted({r[0] for r in data['archives']})
    day_map = {day:i for i,day in enumerate(days)}
    audit: Counter[str] = Counter()
    grouped: dict[tuple[str,str],list[tuple[Event,str,float | None,float | None]]] = defaultdict(list)
    for _,kind,code,exchange,received,state,version,eligible,price,prev,sector,pos,atr in data['events']:
        when = max(stamp(exchange),stamp(received))
        day = when.date().isoformat()
        idx = INDEX.get(when.hour*60+when.minute)
        if idx is None or day not in day_map or day != stamp(exchange).date().isoformat():
            audit['events_outside_session_or_delayed_day'] += 1
            continue
        grouped[(day,code)].append((Event(kind,idx,float(price),state,eligible,'',version),sector,pos,atr))
    codes = sorted({code for _,code in grouped})
    daily_groups: dict[str,dict[str,list[Daily]]] = defaultdict(lambda:defaultdict(list))
    for code,time_key,_open,close,high,low,turnover,created,_id in data['daily']:
        if close is None or high is None or low is None or low <= 0 or high < low:
            audit['invalid_daily'] += 1
            continue
        day = time_key[:10]
        daily_groups[code][day].append(Daily(day,float(close),float(high),float(low),float(turnover or 0)))
        audit['daily_rows_downloaded_after_trade_date'] += str(created)[:10] > day
    daily_by_code: dict[str,list[Daily]] = {}
    for code,by_day in daily_groups.items():
        normalized = []
        for day,rows in sorted(by_day.items()):
            audit['duplicate_daily_rows'] += len(rows)-1
            r = rows[-1]
            conflict = any(max(abs(other.close/r.close-1),abs(other.high/r.high-1),abs(other.low/r.low-1)) > .005
                           for other in rows)
            audit['conflicting_daily_dates_gt50bp'] += conflict
            normalized.append(Daily(day,r.close,r.high,r.low,r.turnover,conflict))
        daily_by_code[code] = normalized
    paths = {}
    for code in codes:
        arrays = [np.full(len(days)*N,np.nan) for _ in range(6)]
        paths[code] = StockPath(code,*arrays,[background(daily_by_code.get(code,[]),day) for day in days])
    seen: set[tuple[str,int]] = set()
    for code,day,minute,mean,high,low,buy,sell,volume in data['minutes']:
        offset = INDEX.get(wall_minute(minute))
        if code not in paths or day not in day_map or offset is None:
            continue
        values = (mean,high,low,volume or 0,buy or 0,sell or 0)
        if (any(v is None or not np.isfinite(v) for v in values) or low <= 0 or high < low
                or mean < low-1e-8 or mean > high+1e-8 or min(values[3:]) < 0):
            audit['invalid_minutes'] += 1
            continue
        point = day_map[day]*N+offset
        if (code,point) in seen:
            raise ValueError('duplicate minute')
        seen.add((code,point))
        p = paths[code]
        for array,value in zip((p.mean,p.high,p.low,p.volume,p.buy,p.sell),values):
            array[point] = value
    opportunities = []
    sectors: Counter[str] = Counter()
    for (day,code),events in sorted(grouped.items()):
        audit['candidate_stock_days_before_theme'] += 1
        matching = sorted((row for row in events if theme_of(row[1])),key=lambda row:row[0].index)
        if not matching:
            audit['excluded_primary_sector'] += 1
            continue
        first,sector,pos,atr = matching[0]
        d = day_map[day]
        p = paths[code]
        bg = p.backgrounds[d]
        sl = slice(d*N,(d+1)*N)
        tape = Tape(day,code,data['names'].get(code,''),p.mean[sl],p.high[sl],p.low[sl],p.buy[sl],p.sell[sl],
                    p.volume[sl],first.index,first.price,bg.prior_close,bg.low20,bg.high20,bg.ma20,
                    tuple(row[0] for row in matching))
        build_features(tape)
        opportunities.append(Opportunity(d,theme_of(sector),sector,tape,bg,pos,atr))
        sectors[sector] += 1
        audit['theme_stock_days'] += 1
        audit['theme_without_valid_prior_daily'] += not bg.valid
        audit['theme_post_gate_coverage_ge90pct'] += np.isfinite(tape.mean[first.index:]).mean() >= .9
    audit['all_regular_minutes'] = len(seen)
    audit['all_codes'] = len(paths)
    audit['theme_codes'] = len({o.tape.code for o in opportunities})
    return Market(days,paths,opportunities,hashlib.sha256(raw).hexdigest(),
                  {key:int(value) for key,value in audit.items()},dict(sectors))
