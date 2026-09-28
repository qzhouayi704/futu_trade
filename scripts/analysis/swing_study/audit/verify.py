"""Cross-file audit identities and date-scope checks, no external I/O."""
import argparse
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path


def read_rows(path: Path) -> list[dict[str,str]]:
    with path.open(encoding='utf-8-sig',newline='') as stream:
        return list(csv.DictReader(stream))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--legacy',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args = parser.parse_args()
    report = json.loads((args.output/'report.json').read_text(encoding='utf-8'))
    assert hashlib.sha256(args.input.read_bytes()).hexdigest() == report['input_sha256']
    legacy = report['legacy_event_time_theme_evidence']
    assert hashlib.sha256(args.legacy.read_bytes()).hexdigest() == legacy['sha256']
    rows = read_rows(args.output/'stock-days.csv')
    assert len({(r['code'],r['day']) for r in rows}) == len(rows)
    for r in rows:
        observed = int(r['observed'])
        assert 0 <= observed <= 330 and 0 <= int(r['max_gap']) <= 330
        assert abs(float(r['coverage_pct'])-observed/330*100) < 1e-10
        assert r['grade'] != 'ALL_330_MINUTES_OBSERVED' or observed == 330
        assert r['evidence'] != 'DAILY_POSITIVE_WITH_NO_ARCHIVE_ROWS' or int(r['archive_rows']) == 0
    windows = read_rows(args.output/'windows.csv')
    for r in windows:
        assert r['start'] in report['version2_dates'] and r['end'] in report['version2_dates']
        assert report['version2_dates'].index(r['end'])-report['version2_dates'].index(r['start'])+1 == int(r['sessions'])
        assert r['complete330'] != 'True' or r['dense_or_complete'] == 'True'
    for horizon,s in report['window_readiness_september_cohort'].items():
        part = [r for r in windows if r['sessions'] == horizon]
        assert len(part) == s['eligible_stock_windows']
        assert sum(r['complete330'] == 'True' for r in part) == s['all330']
        assert sum(r['dense_or_complete'] == 'True' for r in part) == s['dense']
    assert not set(report['version2_dates']) & set(report['calendar']['unexpected_archive_dates'])
    candidates = read_rows(args.output/'candidate-continuity.csv')
    assert len(candidates) == report['candidate_forward_four_sessions']['candidates']
    assert len(legacy['dates']) == 52
    assert legacy['themes']['光伏']['events'] == 0
    print(json.dumps({'status':'PASS','stock_day_rows':len(rows),'window_rows':len(windows),
                      'candidate_rows':len(candidates),'checks':['input_hashes','unique_stock_dates','coverage_bounds',
                       'evidence_semantics','window_counts','calendar_exclusion','legacy_theme_scope']}))


if __name__ == '__main__':
    main()
