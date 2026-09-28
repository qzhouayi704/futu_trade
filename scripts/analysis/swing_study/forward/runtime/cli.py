"""Explicit, local-only synthetic integration check; no background process."""
import argparse
from dataclasses import asdict
from datetime import datetime, time
import json
import logging
from pathlib import Path

from scripts.analysis.minute_entry_study.models import HK
from ..protocol import from_payload
from ..run import registered_hash
from .adapter import replay
from .collector import Collector
from .demo import synthetic_events
from .models import Config, protocol_days


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--enable-local', action='store_true')
    parser.add_argument('--demo', action='store_true', help='Only fictional data; does not test strategy profitability')
    parser.add_argument('--protocol', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if not args.enable_local:
        print('DISABLED: no database, subscription, replay or order started')
        return
    if not args.demo or args.protocol is None or args.output is None:
        parser.error('local CLI currently supports only --demo with explicit --protocol and new --output')
    raw = args.protocol.read_bytes()
    provenance = json.loads(args.protocol.with_name('provenance.json').read_text(encoding='utf-8'))
    if registered_hash(raw) != provenance['protocol_sha256']:
        raise ValueError('registered protocol modified')
    protocol = from_payload(json.loads(raw))
    if args.output.exists():
        raise FileExistsError(args.output)
    args.output.mkdir(parents=True)
    Path('logs').mkdir(exist_ok=True)
    logging.basicConfig(level=logging.INFO, handlers=[logging.StreamHandler(),
        logging.FileHandler('logs/cross_day_research.log', encoding='utf-8')])
    config = Config(args.output/'synthetic-research.sqlite', enabled=True, dataset_kind='SYNTHETIC')
    collector = Collector(config, protocol)
    observations = synthetic_events(protocol)
    reports = []
    days = protocol_days(protocol)[:5]
    try:
        for day in days:
            for event in observations:
                if event.received_at.date().isoformat() == day:
                    collector.observe(event)
            when = datetime.combine(datetime.fromisoformat(day).date(), time(16, 30), HK)
            report = replay(protocol, collector.events(), day, when, config.dataset_kind)
            for exposure in report.exposures:
                collector.observe(exposure)
            reports.append(report)
            before = collector.tracks
            collector.close()
            collector = Collector(config, protocol)
            if before != collector.tracks:
                raise AssertionError('restart did not restore research leases/exposures')
            logging.info('SYNTHETIC %s recovered %d tracks; candidate-5d open=%d', day, len(before),
                         next(a.account.open_positions for a in report.arms if a.name == 'candidate-5d'))
        payload = {'kind': 'SYNTHETIC_PLUMBING_TEST_NOT_STRATEGY_PERFORMANCE',
                   'reports': [asdict(r) for r in reports], 'restart_checks': len(reports),
                   'selection': asdict(collector.selection(when, ('HK.00700',), 2)),
                   'real_subscriptions_started': False, 'orders_sent': False}
        with (args.output/'synthetic-report.json').open('x', encoding='utf-8') as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2, allow_nan=False,
                      default=lambda x: x.isoformat())
        print(f'SYNTHETIC ONLY: {len(observations)} observations; {len(reports)} restart checks; {args.output}')
    finally:
        collector.close()


if __name__ == '__main__':
    main()
