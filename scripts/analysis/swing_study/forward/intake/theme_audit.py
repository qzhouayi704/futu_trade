"""Local-only theme audit of the two already authorized FIRST sequences."""
import argparse
from dataclasses import asdict, dataclass, fields
from datetime import datetime
import gzip
import hashlib
import io
import json
import logging
from pathlib import Path

from ..protocol import SourceHash, from_payload
from ..run import registered_hash
from ..runtime.collector import verify_frozen
from ..runtime.models import local
from .episode_probe import CUTOFF, DAY, HK, MAX_SEQUENCE_ROWS, EpisodeProbe, Sequence, SequenceEvent
from .themes import MAX_SNAPSHOTS, MembershipSnapshot, PlateMembership, SignalReference, ThemeDecision, decide, validate_snapshots


MAX_BYTES = 128*1024


def read_bounded(path: Path, *, compressed: bool) -> tuple[bytes, bytes]:
    with path.open('rb') as stream:
        raw = stream.read(MAX_BYTES+1)
    if len(raw) > MAX_BYTES:
        raise ValueError('source exceeds byte bound')
    if compressed:
        with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
            content = stream.read(MAX_BYTES+1)
    else:
        content = raw
    if len(content) > MAX_BYTES:
        raise ValueError('expanded source exceeds byte bound')
    return raw, content


def load_firsts(path: Path) -> tuple[tuple[SignalReference, ...], str]:
    raw, content = read_bounded(path, compressed=True)
    payload = json.loads(content)
    if not isinstance(payload, dict) or set(payload) != {f.name for f in fields(EpisodeProbe)}:
        raise ValueError('complete explicit authorized probe contract required')
    # Materialize the existing whitelist DTO; no new remote query or raw payload.
    rows = payload.pop('sequences')
    if not isinstance(rows, list) or len(rows) != 2:
        raise ValueError('exactly two authorized sequences required')
    sequences = []
    for row in rows:
        events = row.pop('events')
        if not isinstance(events, list) or not 1 <= len(events) <= MAX_SEQUENCE_ROWS:
            raise ValueError('invalid authorized sequence size')
        sequences.append(Sequence(events=tuple(SequenceEvent(**e) for e in events), **row))
    probe = EpisodeProbe(sequences=tuple(sequences), **payload)
    if (type(probe.schema) is not int or probe.schema != 1
            or probe.kind != 'AUTHORIZED_TWO_FIRST_SEQUENCES' or probe.source != 'PRODUCTION_SQLITE_READ_ONLY'
            or probe.scope != 'TWO_FIRSTS_AT_20260928_113626_AND_THEIR_FIRST_TERMINAL_ONLY'
            or probe.read_only is not True or probe.truncated is not False or probe.performance_result is not None
            or local(datetime.fromisoformat(probe.sequence_cutoff)) != CUTOFF
            or local(datetime.fromisoformat(probe.observed_at)) < CUTOFF):
        raise ValueError('unexpected authorized sequence source contract')
    firsts = []
    for sequence in probe.sequences:
        first = sequence.events[0]
        if (type(sequence.first_row_id) is not int or sequence.first_row_id < 1
                or first.row_id != sequence.first_row_id or first.stage != 'FIRST'
                or type(first.sequence) is not int or first.sequence != 1
                or any(e.code != sequence.code for e in sequence.events)):
            raise ValueError('invalid FIRST anchor')
        when = datetime.fromisoformat(first.emitted_at)
        when = local(when.replace(tzinfo=HK) if when.tzinfo is None else when)
        if when.date().isoformat() != DAY or when > CUTOFF:
            raise ValueError('FIRST outside authorized snapshot')
        firsts.append(SignalReference(f'legacy-sqlite:{first.row_id}', sequence.code, when, first.plate_name))
    if len({e.code for e in firsts}) != 2 or len({e.event_id for e in firsts}) != 2:
        raise ValueError('distinct FIRST anchors required')
    return tuple(firsts), hashlib.sha256(raw).hexdigest()


def load_memberships(path: Path) -> tuple[tuple[MembershipSnapshot, ...], str]:
    raw, content = read_bounded(path, compressed=False)
    envelope = json.loads(content)
    if (set(envelope) != {'schema', 'kind', 'snapshots'} or type(envelope['schema']) is not int
            or envelope['schema'] != 1 or envelope['kind'] != 'THEME_MEMBERSHIP_DIAGNOSTIC'
            or not isinstance(envelope['snapshots'], list) or len(envelope['snapshots']) > MAX_SNAPSHOTS):
        raise ValueError('explicit diagnostic membership envelope required')
    snapshots = []
    for row in envelope['snapshots']:
        row['captured_at'] = datetime.fromisoformat(row['captured_at'])
        row['received_at'] = datetime.fromisoformat(row['received_at'])
        if not isinstance(row['members'], list) or len(row['members']) > 128:
            raise ValueError('bounded member list required')
        row['members'] = tuple(PlateMembership(**m) for m in row['members'])
        snapshots.append(MembershipSnapshot(**row))
    result = tuple(snapshots)
    validate_snapshots(result)
    return result, hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class ThemeAuditReport:
    source_sha256: str
    membership_sha256: str | None
    protocol_sha256: str
    diagnostic_sources: tuple[SourceHash, ...]
    decisions: tuple[ThemeDecision, ...]
    kind: str = 'ARCHIVE_DIAGNOSTIC_THEME_AUDIT'
    taxonomy_basis: str = 'FROZEN_THEME_OF_UNCHANGED_UNION_ACROSS_LABELS'
    policy_basis: str = 'SAME_DAY_CAPTURE_RECEIVED_BY_SIGNAL_EMISSION_DIAGNOSTIC_ONLY'
    prospective_ready: bool = False
    performance_result: None = None
    live_execution_allowed: bool = False
    source_authenticity_independently_certified: bool = False


def audit(input_path: Path, protocol_path: Path, output: Path,
          memberships_path: Path | None = None) -> ThemeAuditReport:
    if output.exists():
        raise FileExistsError(output)
    protocol_raw = protocol_path.read_bytes()
    provenance = json.loads(protocol_path.with_name('provenance.json').read_text(encoding='utf-8'))
    protocol_hash = registered_hash(protocol_raw)
    if protocol_hash != provenance['protocol_sha256']:
        raise ValueError('registered protocol content changed')
    verify_frozen(from_payload(json.loads(protocol_raw)))
    firsts, source_hash = load_firsts(input_path)
    snapshots, membership_hash = load_memberships(memberships_path) if memberships_path else ((), None)
    if any(s.code not in {e.code for e in firsts} for s in snapshots):
        raise ValueError('membership source outside the two authorized stocks')
    sources = tuple(SourceHash('forward/intake/'+name, hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest())
                    for name in ('themes.py', 'theme_audit.py', 'episode_probe.py'))
    report = ThemeAuditReport(source_hash, membership_hash, protocol_hash, sources,
                              tuple(decide(e, snapshots) for e in firsts))
    output.mkdir(parents=True)
    with (output/'theme-report.json').open('x', encoding='utf-8') as stream:
        json.dump(asdict(report), stream, ensure_ascii=False, indent=2, allow_nan=False, default=lambda x: x.isoformat())
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--protocol', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--memberships', type=Path, help='Optional explicit local diagnostic snapshots; never a current database lookup')
    args = parser.parse_args()
    Path('logs').mkdir(exist_ok=True)
    logging.basicConfig(level=logging.INFO, handlers=[logging.StreamHandler(),
        logging.FileHandler('logs/forward_theme_audit.log', encoding='utf-8')])
    report = audit(args.input, args.protocol, args.output, args.memberships)
    for decision in report.decisions:
        logging.info('%s: primary=%s, multi-theme=%s; %s', decision.signal.code,
                     decision.frozen_primary_reason, decision.status, decision.explanation)
    print(json.dumps(asdict(report), ensure_ascii=False, allow_nan=False, default=lambda x: x.isoformat()))


if __name__ == '__main__':
    main()
