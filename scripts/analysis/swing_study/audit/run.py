"""Build a bounded coverage inventory and an explicit expansion-readiness report."""
from __future__ import annotations

import argparse
from collections import Counter,defaultdict
from dataclasses import asdict
from datetime import date,timedelta
import csv
import gzip
import hashlib
import json
import logging
from pathlib import Path
import re

import numpy as np

from scripts.analysis.minute_entry_study.models import INDEX, N, stamp
from ..data import theme_of
from .models import AuditRow,CoverageGrade,DailyEvidence,Evidence,MinuteCoverage,classify,parse_mask,positive_minutes_missing_archive


def equity(code: str, name: str) -> bool:
    return bool(re.fullmatch(r'HK\.\d{5}',code) and int(code[3:]) < 10000 and
                not re.search(r'ETF|Global\s*X|两倍|三倍|反向|盈富基金|安硕|南方恒|恒生指数|华夏恒生',name,re.I))


def statistics(rows: list[AuditRow]) -> dict:
    ratios = [r.volume_ratio for r in rows if r.volume_ratio is not None and r.archive_rows > 0]
    return {'stock_days':len(rows),'codes':len({r.code for r in rows}),
            'dates':len({r.day for r in rows}),'regular_minutes':sum(r.observed for r in rows),
            'median_coverage_pct':float(np.median([r.coverage_pct for r in rows])) if rows else None,
            'median_volume_ratio':float(np.median(ratios)) if ratios else None,
            'grades':dict(Counter(r.grade for r in rows)),'evidence':dict(Counter(r.evidence for r in rows))}


def normalized_daily(raw: list[list]) -> tuple[dict[tuple[str,str],DailyEvidence],dict[str,int]]:
    groups = defaultdict(list)
    counts = Counter()
    for code,time_key,close,high,low,volume,turnover,created in raw:
        if not all(v is not None and np.isfinite(v) and v > 0 for v in (close,high,low)) or high < low:
            counts['invalid_daily_rows'] += 1
            continue
        day = time_key[:10]
        groups[(code,day)].append(DailyEvidence(code,day,float(close),float(high),float(low),
                                               float(volume or 0),float(turnover or 0),str(created)))
        counts['downloaded_after_trade_date_rows'] += str(created)[:10] > day
    result = {}
    for key,values in groups.items():
        r = values[-1]
        conflict = any(max(abs(x.close/r.close-1),abs(x.high/r.high-1),abs(x.low/r.low-1)) > .005 or
                       (max(x.volume,r.volume) > 0 and abs(x.volume-r.volume)/max(x.volume,r.volume) > .01)
                       for x in values)
        counts['duplicate_rows'] += len(values)-1
        counts['conflicting_stock_dates'] += conflict
        result[key] = DailyEvidence(r.code,r.day,r.close,r.high,r.low,r.volume,r.turnover,r.downloaded_at,conflict)
    return result,dict(counts)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--legacy',type=Path,help='Supplementary old signal plate_name evidence')
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    Path('logs').mkdir(exist_ok=True)
    logging.basicConfig(filename='logs/history_data_audit.log',encoding='utf-8',level=logging.INFO)
    raw = args.input.read_bytes()
    data = json.loads(gzip.decompress(raw))
    if data.get('kind') != 'HISTORICAL_DATA_AUDIT':
        raise ValueError('wrong export schema')
    daily,daily_audit = normalized_daily(data['daily'])
    coverage = {}
    for code,day,rows,minutes,total,regular,invalid,_low,_high in data['coverage']:
        if equity(code,data['names'].get(code,'')):
            coverage[(code,day)] = MinuteCoverage(code,day,rows,parse_mask(minutes),float(total or 0),
                                                  float(regular or 0),int(invalid or 0))
    version = {r[0]:int(r[1]) for r in data['archives']}
    observed_days = sorted({day for _,day in coverage})
    versioned_days = [day for day in observed_days if version.get(day,0) >= 2]
    # Frozen official SEHK circular CT/075/25, limited to the audit's date range.
    holidays = {'2026-06-19','2026-07-01'}
    scheduled_days = []
    current = date.fromisoformat(data['start'])
    end = date.fromisoformat(data['end_exclusive'])
    if not ('2026-06-15' <= current.isoformat() < end.isoformat() <= '2026-09-24'):
        raise ValueError('calendar table is scoped only to this audit range')
    while current < end:
        if current.weekday() < 5 and current.isoformat() not in holidays:
            scheduled_days.append(current.isoformat())
        current += timedelta(days=1)
    unexpected_dates = [day for day in observed_days if day not in scheduled_days]
    versioned_days = [day for day in versioned_days if day in scheduled_days]
    first_membership = {}
    theme_memberships = []
    for code,name,plate,created,plate_created,updated,target,enabled in data['memberships']:
        if equity(code,data['names'].get(code,'')) and theme_of(name):
            known = max(str(created)[:10],str(plate_created)[:10])
            first_membership[code] = min(first_membership.get(code,known),known)
            theme_memberships.append([code,name,known,updated,target,enabled])
    themes = set()
    first_candidates = {}
    for code,exchange,received,state,kind,sector,created,source,volume,turnover in data['candidates']:
        if (not equity(code,data['names'].get(code,'')) or not theme_of(sector)
                or state not in {'SETUP','WATCHING','CONFIRMED'}):
            continue
        when = max(stamp(exchange),stamp(received))
        day = when.date().isoformat()
        if day != stamp(exchange).date().isoformat() or when.hour*60+when.minute not in INDEX:
            continue
        themes.add(code)
        key = (code,day)
        first_candidates[key] = min(first_candidates.get(key,when),when)
    # Include absent days only within an explicitly labeled frame. This is an AUDIT
    # frame based on known September names, never an earlier tradable stock universe.
    keys = set(coverage)
    keys.update((code,day) for code in themes for day in observed_days)
    keys.update((code,day) for code,day in daily if day in observed_days and
                first_membership.get(code,'9999') < day and equity(code,data['names'].get(code,'')))
    rows = []
    for code,day in sorted(keys):
        item = coverage.get((code,day),MinuteCoverage(code,day,0,0,0,0,0))
        evidence,ratio = classify(item,daily.get((code,day)))
        rows.append(AuditRow(code,day,item.observed,item.observed/N*100,item.max_gap,item.grade.value,
                             version.get(day,0),item.rows,ratio,evidence.value,
                             first_membership.get(code,'9999') < day,code in themes))
    by_key = {(r.code,r.day):r for r in rows}
    observed_rows = [r for r in rows if r.archive_rows > 0]
    proxy_rows = [r for r in rows if r.historical_membership_proxy and r.archive_version >= 2]
    cohort_rows = [r for r in rows if r.september_theme_cohort and r.archive_version >= 2]
    monthly = {month:statistics([r for r in observed_rows if r.day.startswith(month)])
               for month in sorted({day[:7] for day in observed_days})}
    daily_rows = []
    for day in observed_days:
        s = statistics([r for r in observed_rows if r.day == day])
        daily_rows.append({'day':day,'archive_version':version.get(day,0),'codes':s['codes'],
                           'regular_minutes':s['regular_minutes'],'median_coverage_pct':s['median_coverage_pct'],
                           'complete330':s['grades'].get(CoverageGrade.COMPLETE.value,0),
                           'dense':s['grades'].get(CoverageGrade.DENSE.value,0),
                           'v2_events':sum(count for d,kind,count in data['v2_event_counts'] if d == day),
                           'legacy_signals':sum(r[0] == day for r in data['legacy'])})
    windows = []
    for code in sorted(themes):
        for duration in (1,3,5,10,20):
            for start in range(len(versioned_days)-duration+1):
                days = versioned_days[start:start+duration]
                path = [by_key[(code,day)] for day in days]
                if not path[0].observed:
                    continue
                windows.append({'code':code,'start':days[0],'end':days[-1],'sessions':duration,
                                'complete330':all(r.grade == CoverageGrade.COMPLETE.value for r in path),
                                'dense_or_complete':all(r.grade in {CoverageGrade.COMPLETE.value,CoverageGrade.DENSE.value} for r in path),
                                'minimum_day_coverage_pct':min(r.coverage_pct for r in path),
                                'missing_whole_dates':sum(r.archive_rows == 0 for r in path),
                                'daily_positive_missing':sum(r.evidence == Evidence.NO_ARCHIVE.value for r in path),
                                'membership_proxy_known_before_start':first_membership.get(code,'9999') < days[0]})
    window_summary = {}
    for duration in (1,3,5,10,20):
        part = [r for r in windows if r['sessions']==duration]
        window_summary[str(duration)] = {'eligible_stock_windows':len(part),
            'all330':sum(r['complete330'] for r in part),'dense':sum(r['dense_or_complete'] for r in part),
            'dense_with_earlier_membership_proxy':sum(r['dense_or_complete'] and r['membership_proxy_known_before_start'] for r in part),
            'dense_distinct_stocks':len({r['code'] for r in part if r['dense_or_complete']}),
            'dense_distinct_entry_dates':len({r['start'] for r in part if r['dense_or_complete']}),
            'any_whole_date_missing':sum(r['missing_whole_dates'] > 0 for r in part)}
    raw_groups = defaultdict(list)
    for code,day,minute,count,volume in data['raw_focus']:
        raw_groups[(code,day)].append((minute,float(volume or 0)))
    raw_checks = []
    for (code,day),values in sorted(raw_groups.items()):
        cov = coverage.get((code,day),MinuteCoverage(code,day,0,0,0,0,0))
        missing = positive_minutes_missing_archive(values,cov)
        raw_total = sum(v for _,v in values)
        raw_checks.append({'code':code,'day':day,'raw_minutes_positive_missing_archive':missing,
                           'raw_volume':raw_total,'archive_volume':cov.total_volume,
                           'archive_vs_raw_volume':cov.total_volume/raw_total if raw_total else None})
    legacy_days = sorted({r[0] for r in data['legacy']})
    legacy_backs = sum(str(r[5])[:10] > r[0] for r in data['legacy'])
    candidate_checks = []
    for (code,day),when in sorted(first_candidates.items()):
        if day not in versioned_days:
            continue
        i = versioned_days.index(day)
        future = versioned_days[i+1:i+5]
        candidate_checks.append({'code':code,'day':day,'candidate_at':when.isoformat(),'forward_dates':len(future),
                                 'forward_absent_dates':sum(coverage.get((code,d),MinuteCoverage(code,d,0,0,0,0,0)).rows == 0 for d in future),
                                 'forward_positive_daily_no_archive':sum(by_key[(code,d)].evidence == Evidence.NO_ARCHIVE.value for d in future)})
    legacy_evidence = None
    if args.legacy:
        legacy_raw = args.legacy.read_bytes()
        supplement = json.loads(gzip.decompress(legacy_raw))
        if supplement.get('kind') != 'LEGACY_THEME_EVIDENCE':
            raise ValueError('invalid supplement')
        labeled = supplement['theme_events']
        thematic = [r for r in labeled if theme_of(r[7]) and equity(r[2],data['names'].get(r[2],''))]
        thematic_keys = sorted({(r[2],r[1]) for r in thematic if r[1] in versioned_days})
        theme_windows = {}
        for duration in (1,3,5,10,20):
            eligible = complete = dense = missing = 0
            dates = set()
            for code,day in thematic_keys:
                start = versioned_days.index(day)
                if start+duration > len(versioned_days):
                    continue
                eligible += 1
                dates.add(day)
                path = [coverage.get((code,d),MinuteCoverage(code,d,0,0,0,0,0))
                        for d in versioned_days[start:start+duration]]
                complete += all(c.grade == CoverageGrade.COMPLETE for c in path)
                dense += all(c.grade in {CoverageGrade.COMPLETE,CoverageGrade.DENSE} for c in path)
                missing += any(c.rows == 0 for c in path)
            theme_windows[str(duration)] = {'labeled_stock_dates_with_forward_window':eligible,
                                            'entry_dates':len(dates),'all330':complete,'dense':dense,
                                            'any_whole_date_missing':missing}
        legacy_evidence = {'sha256':hashlib.sha256(legacy_raw).hexdigest(),'nonempty_plate_events':len(labeled),
                           'start':min(r[1] for r in labeled),'end':max(r[1] for r in labeled),
                           'dates':sorted({r[1] for r in labeled}),'thematic_events':len(thematic),
                           'thematic_stock_dates':len(thematic_keys),'thematic_codes':len({r[2] for r in thematic}),
                           'sources':dict(Counter(r[3] for r in labeled)),
                           'themes':{theme:{'events':sum(theme_of(r[7])==theme for r in thematic),
                                            'codes':len({r[2] for r in thematic if theme_of(r[7])==theme})}
                                     for theme in ('AI','科技','医药','芯片','光伏')},
                           'window_readiness':theme_windows,
                           'note':'Legacy capital_trend labels are contemporaneous evidence, not V2 or necessarily BUY signals'}
    report = {'schema':1,'input_sha256':hashlib.sha256(raw).hexdigest(),'exported_at':data['exported_at'],
              'source_range':[data['start'],data['end_exclusive']],'inventory':data['inventory'],
              'calendar':{'source':'https://www.hkex.com.hk/-/media/HKEX-Market/Services/Circulars-and-Notices/Participant-and-Members-Circulars/SEHK/2025/ce_SEHK_CT_075_2025.pdf',
                          'scheduled_dates':scheduled_days,'unexpected_archive_dates':unexpected_dates,
                          'scheduled_dates_without_any_archive':[d for d in scheduled_days if d not in observed_days],
                          'note':'scheduled trading days; ad hoc interruptions not separately reconstructed'},
              'observed_archive_dates':observed_days,'version2_dates':versioned_days,
              'daily_normalization':daily_audit,'all_observed_equity_stock_days':statistics(observed_rows),
              'historical_membership_proxy_stock_days':statistics(proxy_rows),
              'september_theme_cohort_stock_days':statistics(cohort_rows),'september_theme_codes':len(themes),
              'monthly_observed':monthly,'window_readiness_september_cohort':window_summary,
              'legacy':{'rows':len(data['legacy']),'dates':legacy_days,'sources':dict(Counter(str(r[2]) for r in data['legacy'])),
                        'created_after_signal_date':legacy_backs,'raw_detail_top_level_keys':data['legacy_detail_keys'],
                        'top_level_theme_count':len(supplement['theme_events']) if args.legacy else None,
                        'note':'v1 export omitted the plate_name key from its theme counter; corrected using supplement'},
              'legacy_event_time_theme_evidence':legacy_evidence,
              'raw_focus_checks':raw_checks,'raw_days':data['raw_days'],
              'candidate_forward_four_sessions':{'candidates':len(candidate_checks),
                   'with_any_absent_forward_date':sum(r['forward_absent_dates'] > 0 for r in candidate_checks),
                   'with_daily_positive_absent_forward_date':sum(r['forward_positive_daily_no_archive'] > 0 for r in candidate_checks),
                   'full_four_forward_dates':sum(r['forward_dates'] == 4 for r in candidate_checks),
                   'full_window_any_absent_date':sum(r['forward_dates'] == 4 and r['forward_absent_dates'] > 0 for r in candidate_checks),
                   'full_window_daily_positive_absent_date':sum(r['forward_dates'] == 4 and r['forward_positive_daily_no_archive'] > 0 for r in candidate_checks)},
              'current_theme_memberships':len(theme_memberships),'current_theme_codes':len(first_membership),
              'limitations':['scheduled calendar verified; ad hoc interruptions not independently reconstructed',
                            '330 observed minutes do not certify complete ticks within each minute',
                            'historical created_at membership is a current-survivor first-seen proxy, not full PIT membership',
                            'post-selected September cohort windows are diagnostics, not an eligible backtest universe',
                            'daily volume comparison mixes source revisions and auctions; discrepancies are evidence, not exact missing-volume counts',
                            'no gap is certified as no-trade; raw checks are limited to three stocks and retained dates']}
    args.output.mkdir(parents=True)
    (args.output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    for name,records in [('stock-days.csv',[asdict(r) for r in rows]),('dates.csv',daily_rows),
                         ('windows.csv',windows),('candidate-continuity.csv',candidate_checks),('raw-cross-check.csv',raw_checks)]:
        if records:
            with (args.output/name).open('w',encoding='utf-8-sig',newline='') as stream:
                writer = csv.DictWriter(stream,fieldnames=list(records[0]))
                writer.writeheader();writer.writerows(records)
    logging.info('Audit complete: input=%s stock_days=%s windows=%s',report['input_sha256'],len(rows),len(windows))
    print(json.dumps({key:report[key] for key in ('input_sha256','monthly_observed','daily_normalization',
                      'window_readiness_september_cohort','september_theme_cohort_stock_days',
                      'candidate_forward_four_sessions','raw_focus_checks')},ensure_ascii=False),flush=True)
    print(json.dumps({'legacy_event_time_theme_evidence':legacy_evidence,'unexpected_archive_dates':unexpected_dates},ensure_ascii=False),flush=True)


if __name__ == '__main__':
    main()
