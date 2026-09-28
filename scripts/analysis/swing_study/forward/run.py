"""Create/check a local frozen protocol. Never starts any live or paper process."""
import argparse
from datetime import datetime
import gzip
import hashlib
import json
import logging
from pathlib import Path

from scripts.analysis.minute_entry_study.models import HK
from .protocol import DayEvidence, encoded, evaluate, freeze, from_payload, source_hashes


def registered_hash(stored: bytes) -> str:
    # Hash the canonical registration, not OS-dependent CRLF/LF text encoding.
    return hashlib.sha256(encoded(from_payload(json.loads(stored))).encode('utf-8')).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--probe', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument('--historical-input', type=Path, help='Register a new protocol with current source hashes')
    choice.add_argument('--protocol', type=Path, help='Check an existing protocol without changing its registration')
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    now = datetime.now(HK)
    probe_raw = args.probe.read_bytes()
    probe = json.loads(gzip.decompress(probe_raw))
    if probe.get('kind') != 'FORWARD_READINESS_PROBE' or probe.get('read_only') is not True:
        raise ValueError('unsupported readiness evidence')
    if args.protocol:
        stored = args.protocol.read_bytes()
        provenance = json.loads(args.protocol.with_name('provenance.json').read_text(encoding='utf-8'))
        if registered_hash(stored) != provenance['protocol_sha256']:
            raise ValueError('registered protocol content changed; create a new registration')
        protocol = from_payload(json.loads(stored))
    else:
        historical_raw = args.historical_input.read_bytes()
        historical = json.loads(gzip.decompress(historical_raw))
        if historical.get('kind') != 'LEGACY_SWING_DATA':
            raise ValueError('not the preceding legacy study source')
        protocol = freeze(now, hashlib.sha256(historical_raw).hexdigest())
    minute_rows = {r[0]: r[1] for r in probe['minute_days']}
    evidence = tuple(DayEvidence(r[0], r[1], minute_rows.get(r[0], 0)) for r in probe['archives'])
    readiness = evaluate(protocol, datetime.fromisoformat(probe['observed_at']), evidence, now, source_hashes())
    args.output.mkdir(parents=True)
    with (args.output/'protocol.json').open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(encoded(protocol))
    with (args.output/'readiness.json').open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(encoded(readiness))
    provenance = {'probe_sha256': hashlib.sha256(probe_raw).hexdigest(),
                  'protocol_sha256': hashlib.sha256(encoded(protocol).encode()).hexdigest(),
                  'readiness_sha256': hashlib.sha256(encoded(readiness).encode()).hexdigest(),
                  'hash_basis': 'UTF8_CANONICAL_DATACLASS_JSON_LF',
                  'mode': 'LOCAL_PROTOCOL_AND_READ_ONLY_CHECK_ONLY'}
    with (args.output/'provenance.json').open('x', encoding='utf-8') as stream:
        json.dump(provenance, stream, indent=2)
    Path('logs').mkdir(exist_ok=True)
    logging.basicConfig(level=logging.INFO, handlers=[logging.StreamHandler(),
                        logging.FileHandler('logs/forward_study_readiness.log', encoding='utf-8')])
    logging.info('Frozen registration %s; state=%s; prospective dates=%d; no runner started',
                 protocol.registered_at, readiness.state, len(readiness.post_freeze_archived_dates))
    print(encoded(readiness))


if __name__ == '__main__':
    main()
