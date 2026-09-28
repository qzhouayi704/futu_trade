"""Apply frozen historical selections to an independently fetched partial day."""
from __future__ import annotations
import argparse
from dataclasses import asdict
import gzip
import json
from pathlib import Path

import numpy as np

from .models import Exit, Rule, load
from .replay import Costs, replay
from .rules import signal_index
from .run import clock, serialize_trade


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--report',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    data = load(args.input)
    source = json.loads(gzip.decompress(args.input.read_bytes()))
    selections = json.loads(args.report.read_text(encoding='utf-8'))
    result = {'as_of':source['as_of'],'input_sha256':data.sha256,'partial_day':True,'cases':[]}
    for tape in data.tapes:
        observed = np.flatnonzero(np.isfinite(tape.mean))
        case = {'day':tape.day,'code':tape.code,'gate':clock(tape.gate),'anchor':tape.anchor,
                'last_minute':clock(int(observed[-1])),'last_mean':float(tape.mean[observed[-1]]),
                'subsequent_high':float(np.nanmax(tape.high[tape.gate+1:])),
                'subsequent_low':float(np.nanmin(tape.low[tape.gate+1:])),
                'rules':[]}
        for item in selections['results']:
            if item['variant'] != 'tuned':
                continue
            rule = Rule(**item['rule'])
            index = signal_index(tape,rule)
            record = {'family':rule.family,'signal':clock(index)}
            if index is not None:
                trade = replay(tape,index,rule,Exit(**item['exit']),Costs())
                if trade:
                    record['trade'] = serialize_trade(trade,rule.family,'partial_day')
                    if trade.exit is None:
                        record['status'] = 'NOT_YET_EXITED_AT_CUTOFF'
            case['rules'].append(record)
        result['cases'].append(case)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))


if __name__ == '__main__':
    main()
