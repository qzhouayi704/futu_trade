"""Audit an existing read-only snapshot and optionally quarantine its signals."""
import argparse
from dataclasses import asdict
import hashlib
import json
import logging
from pathlib import Path

from ..protocol import from_payload
from ..run import registered_hash
from ..runtime.collector import Collector, verify_frozen
from ..runtime.models import Config
from .models import DIAGNOSTIC, load
from .normalize import assess


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--protocol', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--stage-diagnostic-signals', action='store_true', help='Explicit local quarantine only, never a live dataset')
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    raw = args.protocol.read_bytes()
    provenance = json.loads(args.protocol.with_name('provenance.json').read_text(encoding='utf-8'))
    if registered_hash(raw) != provenance['protocol_sha256']:
        raise ValueError('registered protocol content changed')
    protocol = from_payload(json.loads(raw))
    verify_frozen(protocol)
    snapshot = load(args.input)
    report = assess(snapshot, protocol)
    args.output.mkdir(parents=True)
    Path('logs').mkdir(exist_ok=True)
    logging.basicConfig(level=logging.INFO, handlers=[logging.StreamHandler(),
        logging.FileHandler('logs/forward_source_intake.log', encoding='utf-8')])
    if args.stage_diagnostic_signals:
        config = Config(args.output/'diagnostic-signals.sqlite', enabled=True, dataset_kind=DIAGNOSTIC)
        collector = Collector(config, protocol)
        try:
            for event in report.normalized:
                collector.observe(event)
            expected = collector.events()
        finally:
            collector.close()
        recovered = Collector(config, protocol)
        try:
            if recovered.events() != expected:
                raise AssertionError('diagnostic journal restart mismatch')
            if any(recovered.observe(e) for e in expected):
                raise AssertionError('repeated source identity was not idempotent')
        finally:
            recovered.close()
    payload = asdict(report)
    payload['normalized'] = [asdict(e) for e in report.normalized]
    payload['staged_diagnostic_signals'] = len(report.normalized) if args.stage_diagnostic_signals else 0
    payload['protocol_sha256'] = registered_hash(raw)
    payload['source_columns'] = [asdict(c) for c in snapshot.columns]
    payload['intake_sources'] = [{'path': f'forward/intake/{p.name}', 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
                                 for p in sorted(Path(__file__).parent.glob('*.py'))]
    with (args.output/'intake-report.json').open('x', encoding='utf-8') as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2, allow_nan=False, default=lambda x: x.isoformat())
    logging.info('Read-only source %s: %d normalized, %d rejected; diagnostic only; no performance replay',
                 snapshot.observed_at.isoformat(), len(report.normalized), len(report.rejections))
    print(json.dumps({'observed_at': report.observed_at, 'stocks': [asdict(s) for s in report.stocks],
        'minute_coverage': [asdict(m) for m in report.minute_coverage], 'blockers': report.blockers,
        'prospective_ready': report.prospective_ready, 'performance_result': None}, ensure_ascii=False))


if __name__ == '__main__':
    main()
