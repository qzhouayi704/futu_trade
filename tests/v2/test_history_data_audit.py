"""Classification boundaries using synthetic independent data sources."""
import unittest

from scripts.analysis.minute_entry_study.models import N,WALL
from scripts.analysis.swing_study.audit.models import (
    CoverageGrade,DailyEvidence,Evidence,MinuteCoverage,classify,parse_mask,positive_minutes_missing_archive,
)
from scripts.analysis.swing_study.audit.run import normalized_daily


def day(volume: float = 1000, conflict: bool = False) -> DailyEvidence:
    return DailyEvidence('HK.00100','2026-09-17',100,101,99,volume,volume*100,'2026-09-18',conflict)


def cov(mask: int = 0, volume: float = 0) -> MinuteCoverage:
    return MinuteCoverage('HK.00100','2026-09-17',mask.bit_count(),mask,volume,volume,0)


class HistoryDataAuditTests(unittest.TestCase):
    def test_mask_excludes_lunch_auction_duplicates_and_bad_input(self):
        mask = parse_mask('09:30,09:30,11:59,12:00,12:30,13:00,16:00,nan,aa:bb')
        self.assertEqual(mask.bit_count(),3)

    def test_full_minute_observation_is_separate_from_tick_volume(self):
        c = cov((1<<N)-1,500)
        self.assertEqual(c.grade,CoverageGrade.COMPLETE)
        self.assertEqual(classify(c,day())[0],Evidence.LOW_VOLUME)

    def test_near_full_but_long_outage_not_dense(self):
        mask = ((1<<N)-1) ^ (((1<<10)-1)<<10)
        self.assertEqual(cov(mask).max_gap,10)
        self.assertEqual(cov(mask).grade,CoverageGrade.GAPPED)

    def test_short_gaps_dense_not_complete(self):
        mask = ((1<<N)-1) ^ (1<<10)
        self.assertEqual(cov(mask).grade,CoverageGrade.DENSE)

    def test_absence_without_source_is_unknown(self):
        self.assertEqual(classify(cov(),None),(Evidence.UNKNOWN,None))

    def test_zero_daily_volume_not_certified_no_trade(self):
        self.assertEqual(classify(cov(),day(0))[0],Evidence.EMPTY_DAILY)

    def test_positive_daily_no_archived_rows_is_cross_source_gap(self):
        self.assertEqual(classify(cov(),day()),(Evidence.NO_ARCHIVE,0))

    def test_daily_conflict_takes_precedence_over_missing_archive_claim(self):
        self.assertEqual(classify(cov(),day(conflict=True)),(Evidence.CONFLICT,None))

    def test_no_invention_of_raw_trades_in_missing_minutes(self):
        c = cov(parse_mask('09:30,09:31'))
        self.assertEqual(positive_minutes_missing_archive([('09:31',10),('09:32',30),('09:33',0),('16:00',100)],c),1)

    def test_normalization_conflicting_volume_is_not_a_valid_denominator(self):
        values = [['HK.00100','2026-09-17',100,101,99,1000,100000,'2026-09-18'],
                  ['HK.00100','2026-09-17 00:00:00',100,101,99,100000,100000,'2026-09-19']]
        result,audit = normalized_daily(values)
        self.assertTrue(result[('HK.00100','2026-09-17')].conflict)
        self.assertEqual(audit['duplicate_rows'],1)


if __name__ == '__main__':
    unittest.main()
