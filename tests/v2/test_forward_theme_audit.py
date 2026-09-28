"""Causal membership selection and diagnostic-only file integration."""
from dataclasses import asdict, fields, replace
from datetime import datetime, timedelta, timezone
import gzip
import json
from pathlib import Path
import tempfile
import unittest

from scripts.analysis.swing_study.forward.intake.episode_probe import CUTOFF, HK, EpisodeProbe, Sequence, SequenceEvent
from scripts.analysis.swing_study.forward.intake.theme_audit import MAX_BYTES, audit, load_firsts, load_memberships, read_bounded
from scripts.analysis.swing_study.forward.intake.themes import (
    MembershipSnapshot, PlateMembership, SignalReference, decide, validate_snapshots,
)
from scripts.analysis.swing_study.forward.protocol import encoded, freeze
from scripts.analysis.swing_study.forward.run import registered_hash


def at(clock='09:35:00', day='2026-09-28'):
    return datetime.fromisoformat(day+'T'+clock).replace(tzinfo=HK)


def snapshot(**changes):
    base = MembershipSnapshot('mock:1', 'HK.00175', 'MOCK_POINT_IN_TIME_SOURCE', 'mock-v1',
        at('09:30:00'), at('09:30:01'), True, 'PIT_CAPTURE',
        (PlateMembership('MOCK.CAR', '新能源车企'), PlateMembership('MOCK.CHIP', '半导体'),
         PlateMembership('MOCK.AI', '人工智能')))
    return replace(base, **changes)


class ThemeDecisionTest(unittest.TestCase):
    def setUp(self):
        self.signal = SignalReference('mock:first', 'HK.00175', at(), '新能源车企')

    def test_union_of_multiple_labels_keeps_primary_baseline_and_no_buy_permission(self):
        result = decide(self.signal, (snapshot(),))
        self.assertEqual(result.status, 'MATCHED')
        self.assertEqual(result.matched_themes, ('AI', '芯片'))
        self.assertIsNone(result.frozen_primary_theme)
        self.assertEqual(result.frozen_primary_reason, 'PRIMARY_LABEL_NO_MATCH')
        self.assertEqual(len(result.matched_members), 2)
        self.assertFalse(result.buy_authorized)
        self.assertFalse(result.source_authenticity_independently_certified)

    def test_missing_membership_is_unknown_not_exclusion_even_if_primary_matches(self):
        for primary in ('新能源车企', '回港中概股', '科技', '', None):
            result = decide(replace(self.signal, primary_label=primary), ())
            self.assertEqual(result.status, 'UNKNOWN')
            self.assertEqual(result.reason, 'MEMBERSHIP_SNAPSHOT_MISSING')
        self.assertEqual(decide(replace(self.signal, primary_label='科技'), ()).frozen_primary_theme, '科技')

    def test_complete_empty_or_nonmatching_membership_is_excluded(self):
        for members in ((), (PlateMembership('MOCK.CAR', '新能源车企'),)):
            result = decide(self.signal, (snapshot(members=members),))
            self.assertEqual(result.status, 'EXCLUDED')
            self.assertEqual(result.reason, 'NO_TARGET_THEME_IN_COMPLETE_SNAPSHOT')

    def test_future_received_snapshot_cannot_backfill(self):
        future = snapshot(received_at=at('09:35:01'))
        self.assertEqual(decide(self.signal, (future,)).reason, 'SNAPSHOT_NOT_YET_KNOWN')
        earlier = snapshot(snapshot_id='mock:earlier', members=())
        self.assertEqual(decide(self.signal, (earlier, future)).status, 'EXCLUDED')

    def test_later_removal_does_not_change_past_but_applies_to_later_signals(self):
        removed = snapshot(snapshot_id='mock:removed', captured_at=at('09:40:00'),
                           received_at=at('09:40:01'), members=())
        self.assertEqual(decide(self.signal, (snapshot(), removed)).status, 'MATCHED')
        later_signal = replace(self.signal, emitted_at=at('09:41:00'))
        self.assertEqual(decide(later_signal, (snapshot(), removed)).status, 'EXCLUDED')

    def test_latest_incomplete_does_not_fallback_to_complete(self):
        incomplete = snapshot(snapshot_id='mock:incomplete', captured_at=at('09:34:00'),
                              received_at=at('09:34:01'), complete=False)
        result = decide(self.signal, (snapshot(), incomplete))
        self.assertEqual(result.reason, 'MEMBERSHIP_SNAPSHOT_INCOMPLETE')
        self.assertEqual(result.snapshot_ids, ('mock:incomplete',))

    def test_old_snapshot_arriving_late_does_not_replace_newer_capture(self):
        older = snapshot(received_at=at('09:34:59'))
        newer = snapshot(snapshot_id='mock:newer', captured_at=at('09:34:00'),
                         received_at=at('09:34:01'), members=())
        self.assertEqual(decide(self.signal, (older, newer)).status, 'EXCLUDED')

    def test_current_lookup_and_synthetic_never_admitted_as_pit(self):
        for evidence in ('CURRENT_LOOKUP', 'SYNTHETIC'):
            self.assertEqual(decide(self.signal, (snapshot(evidence=evidence),)).reason,
                             'NOT_POINT_IN_TIME_EVIDENCE')

    def test_previous_date_and_other_stock_cannot_supply_missing_evidence(self):
        previous = snapshot(captured_at=at(day='2026-09-25'), received_at=at(day='2026-09-25'))
        self.assertEqual(decide(self.signal, (previous,)).reason, 'NO_SAME_DAY_SNAPSHOT')
        self.assertEqual(decide(self.signal, (snapshot(code='HK.09999'),)).reason, 'MEMBERSHIP_SNAPSHOT_MISSING')

    def test_same_time_conflict_is_not_selected_by_order(self):
        conflict = snapshot(snapshot_id='mock:conflict', members=())
        for rows in ((snapshot(), conflict), (conflict, snapshot())):
            self.assertEqual(decide(self.signal, rows).reason, 'CONFLICTING_LATEST_SNAPSHOTS')

    def test_duplicate_ids_idempotent_but_conflicting_identity_rejected(self):
        self.assertEqual(decide(self.signal, (snapshot(), snapshot())).snapshot_ids, ('mock:1',))
        with self.assertRaisesRegex(ValueError, 'identity reused'):
            decide(self.signal, (snapshot(), snapshot(members=())))

    def test_timezone_normalization_boundary_and_explicit_times(self):
        same_instant = snapshot(captured_at=self.signal.emitted_at.astimezone(timezone.utc),
                                received_at=self.signal.emitted_at.astimezone(timezone.utc))
        self.assertEqual(decide(self.signal, (same_instant,)).status, 'MATCHED')
        for changes in ({'captured_at': at().replace(tzinfo=None)},
                        {'received_at': at('09:29:59')}, {'complete': 1}, {'evidence': 'archive'},
                        {'source_version': ''}, {'code': 'US.AAPL'}, {'members': []},
                        {'members': (PlateMembership('same', 'AI'), PlateMembership('same', '软件'))}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                snapshot(**changes)
        with self.assertRaises(ValueError):
            replace(self.signal, emitted_at=at().replace(tzinfo=None))

    def test_frozen_single_label_priority_unchanged_and_all_five_themes_supported(self):
        rows = tuple(PlateMembership(str(i), name) for i, name in enumerate(
            ('AI芯片', '科技', '医药', '芯片', '光伏', '软件')))
        result = decide(self.signal, (snapshot(members=rows),))
        self.assertEqual(result.matched_themes, ('AI', '科技', '医药', '芯片', '光伏'))
        single = decide(self.signal, (snapshot(members=(rows[0],)),))
        self.assertEqual(single.matched_themes, ('AI',))

    def test_snapshot_count_bound(self):
        with self.assertRaises(ValueError):
            validate_snapshots((snapshot(),)*257)


class ThemeAuditFileTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='theme-audit-')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.input = self.root/'two.json.gz'
        sequences = []
        for row_id, code, label in ((1, 'HK.00175', '新能源车企'), (2, 'HK.09999', '回港中概股')):
            values = {f.name: None for f in fields(SequenceEvent)}
            values.update(row_id=row_id, code=code, emitted_at=at().replace(tzinfo=None).isoformat(),
                          persisted_utc='2026-09-28 01:35:00', stage='FIRST', sequence=1, plate_name=label)
            sequences.append(Sequence(row_id, code, (SequenceEvent(**values),), False))
        self.probe = EpisodeProbe(at('12:00:00').isoformat(), CUTOFF.isoformat(), tuple(sequences), .01)
        self.write_probe(asdict(self.probe))
        self.protocol = self.root/'protocol.json'
        raw = encoded(freeze(at(day='2026-09-24'), 'mock-history')).encode()
        self.protocol.write_bytes(raw)
        (self.root/'provenance.json').write_text(json.dumps({'protocol_sha256': registered_hash(raw)}), encoding='utf-8')

    def write_probe(self, payload):
        self.input.write_bytes(gzip.compress(json.dumps(payload).encode(), mtime=0))

    def write_memberships(self, rows):
        path = self.root/'memberships.json'
        path.write_text(json.dumps({'schema': 1, 'kind': 'THEME_MEMBERSHIP_DIAGNOSTIC',
            'snapshots': [asdict(s) for s in rows]}, default=lambda x: x.isoformat()), encoding='utf-8')
        return path

    def test_end_to_end_missing_is_unknown_no_returns_and_no_overwrite(self):
        output = self.root/'output'
        report = audit(self.input, self.protocol, output)
        self.assertEqual([d.status for d in report.decisions], ['UNKNOWN', 'UNKNOWN'])
        self.assertTrue(all(d.frozen_primary_theme is None for d in report.decisions))
        saved = json.loads((output/'theme-report.json').read_text(encoding='utf-8'))
        self.assertIsNone(saved['performance_result'])
        self.assertFalse(saved['prospective_ready'])
        self.assertFalse(saved['live_execution_allowed'])
        self.assertEqual(len(saved['diagnostic_sources']), 3)
        with self.assertRaises(FileExistsError):
            audit(self.input, self.protocol, output)

    def test_membership_roundtrip_and_diagnostic_only_match(self):
        path = self.write_memberships((snapshot(),))
        rows, digest = load_memberships(path)
        self.assertEqual(rows, (snapshot(),))
        self.assertEqual(len(digest), 64)
        report = audit(self.input, self.protocol, self.root/'output', path)
        self.assertEqual([d.status for d in report.decisions], ['MATCHED', 'UNKNOWN'])
        self.assertEqual(report.membership_sha256, digest)
        self.assertFalse(report.prospective_ready)

    def test_malformed_and_implicit_source_contract_rejected(self):
        for field, value in (('scope', 'ALL_STOCKS'), ('read_only', False), ('truncated', True),
                             ('sequence_cutoff', (CUTOFF+timedelta(seconds=1)).isoformat()),
                             ('sequences', []), ('schema', True)):
            payload = asdict(self.probe)
            payload[field] = value
            self.write_probe(payload)
            with self.subTest(field=field), self.assertRaises(ValueError):
                load_firsts(self.input)
        payload = asdict(self.probe)
        del payload['scope']
        self.write_probe(payload)
        with self.assertRaises(ValueError):
            load_firsts(self.input)

    def test_memberships_outside_authorized_two_stocks_rejected(self):
        path = self.write_memberships((snapshot(code='HK.00699'),))
        with self.assertRaisesRegex(ValueError, 'outside'):
            audit(self.input, self.protocol, self.root/'output', path)
        self.assertFalse((self.root/'output').exists())

    def test_changed_protocol_rejected_before_output(self):
        (self.root/'provenance.json').write_text(json.dumps({'protocol_sha256': '0'*64}), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'protocol content changed'):
            audit(self.input, self.protocol, self.root/'output')
        self.assertFalse((self.root/'output').exists())

    def test_byte_bounds_for_compressed_and_expanded_input(self):
        self.input.write_bytes(b'x'*(MAX_BYTES+1))
        with self.assertRaises(ValueError):
            read_bounded(self.input, compressed=False)
        self.input.write_bytes(gzip.compress(b'x'*(MAX_BYTES+1)))
        with self.assertRaises(ValueError):
            read_bounded(self.input, compressed=True)


if __name__ == '__main__':
    unittest.main()
