#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""每手股数提供者测试：快照解析、缓存、整手取整、未知时放行。"""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from simple_trade.services.market_data.lot_size_provider import (
    LotSizeProvider, DEFAULT_LOT_SIZE,
)


class _FakeRow(dict):
    """模拟 DataFrame 的一行（row.get 语义与 dict 一致）。"""


class _FakeFrame:
    """模拟富途快照返回的 DataFrame（只需 empty / iterrows）。"""

    def __init__(self, rows):
        self._rows = rows

    @property
    def empty(self):
        return not self._rows

    def iterrows(self):
        return enumerate(self._rows)


class _FakeFutuClient:
    """可用性可控 + 记录调用次数的假富途客户端。"""

    def __init__(self, table, available=True):
        self.table = table          # {code: lot_size}
        self.available = available
        self.calls = 0

    def is_available(self):
        return self.available

    def get_market_snapshot(self, codes):
        self.calls += 1
        if not self.available:
            return -1, "富途API不可用"
        rows = [
            _FakeRow(code=c, lot_size=self.table[c])
            for c in codes if c in self.table
        ]
        return 0, _FakeFrame(rows)


class TestLotSizeProvider(unittest.TestCase):

    def test_get_reads_lot_size_from_snapshot(self):
        client = _FakeFutuClient({'HK.00700': 100, 'HK.09999': 50})
        p = LotSizeProvider(client)
        self.assertEqual(p.get('HK.00700'), 100)
        self.assertEqual(p.get('HK.09999'), 50)  # 每手不足100股的股票

    def test_get_caches_and_does_not_refetch(self):
        client = _FakeFutuClient({'HK.00700': 100})
        p = LotSizeProvider(client)
        self.assertEqual(p.get('HK.00700'), 100)
        self.assertEqual(p.get('HK.00700'), 100)
        self.assertEqual(client.calls, 1)  # 第二次命中缓存

    def test_get_returns_none_when_futu_unavailable(self):
        client = _FakeFutuClient({'HK.00700': 100}, available=False)
        p = LotSizeProvider(client)
        self.assertIsNone(p.get('HK.00700'))
        self.assertEqual(p.get_or_default('HK.00700'), DEFAULT_LOT_SIZE)

    def test_get_returns_none_for_unknown_code(self):
        p = LotSizeProvider(_FakeFutuClient({'HK.00700': 100}))
        self.assertIsNone(p.get('HK.99999'))

    def test_prefetch_batches_and_fills_cache(self):
        client = _FakeFutuClient({'HK.00700': 100, 'HK.09999': 50, 'HK.01810': 200})
        p = LotSizeProvider(client)
        got = p.prefetch(['HK.00700', 'HK.09999', 'HK.01810', 'HK.00700'])
        self.assertEqual(got, {'HK.00700': 100, 'HK.09999': 50, 'HK.01810': 200})
        self.assertEqual(client.calls, 1)  # 去重后一次批量
        p.get('HK.01810')
        self.assertEqual(client.calls, 1)  # 走缓存

    def test_floor_to_lot_uses_real_lot_size(self):
        p = LotSizeProvider(_FakeFutuClient({'HK.09999': 50, 'HK.01810': 200}))
        # 每手50股：120 → 100（旧的硬编码100会取到100，这里一致；关键看非100手）
        self.assertEqual(p.floor_to_lot('HK.09999', 120), 100)
        self.assertEqual(p.floor_to_lot('HK.09999', 80), 50)   # 旧逻辑会抹成0
        self.assertEqual(p.floor_to_lot('HK.01810', 350), 200)  # 每手200，旧逻辑会下出非整手300

    def test_floor_to_lot_falls_back_to_default_when_unknown(self):
        p = LotSizeProvider(_FakeFutuClient({}, available=False))
        self.assertEqual(p.floor_to_lot('HK.00700', 250), 200)  # 回退100
        self.assertEqual(p.floor_to_lot('HK.00700', 0), 0)
        self.assertEqual(p.floor_to_lot('HK.00700', -10), 0)

    def test_is_valid_quantity(self):
        p = LotSizeProvider(_FakeFutuClient({'HK.09999': 50}))
        self.assertTrue(p.is_valid_quantity('HK.09999', 50))
        self.assertTrue(p.is_valid_quantity('HK.09999', 150))
        self.assertFalse(p.is_valid_quantity('HK.09999', 70))
        self.assertFalse(p.is_valid_quantity('HK.09999', 0))

    def test_is_valid_quantity_passes_when_lot_unknown(self):
        # 每手未知时不拦截，交由券商判定（不因取不到 lot_size 就误拒单）
        p = LotSizeProvider(_FakeFutuClient({}, available=False))
        self.assertTrue(p.is_valid_quantity('HK.00700', 37))


if __name__ == '__main__':
    unittest.main()
