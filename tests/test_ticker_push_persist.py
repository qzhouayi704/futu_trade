#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TickerPushHandler 逐笔落库攒批测试

验证 2026-07 架构审查修复：SDK 推送线程只进内存缓冲（无磁盘 I/O），
由 flusher 经 DatabaseWriteQueue 批量落库；失败塞回重试幂等；缓冲有硬上限。
"""

import os
import sqlite3
import tempfile
import unittest
from types import SimpleNamespace

import pandas as pd

from simple_trade.api.ticker_push_handler import TickerPushHandler
from simple_trade.database.core.connection_manager import ConnectionManager
from simple_trade.database.core.write_queue import DatabaseWriteQueue
from simple_trade.database.models.business_tables import BusinessTables


class _FakeDBManager:
    """最小 db_manager 替身：真实 ConnectionManager + 真实写队列"""

    def __init__(self, path: str):
        self.conn_manager = ConnectionManager(path)
        self.write_queue = DatabaseWriteQueue()
        self.write_queue.start()

    def close(self):
        self.write_queue.shutdown(timeout=5.0)


def _make_df(n: int, start_seq: int = 1, price: float = 10.0):
    return pd.DataFrame({
        'code': ['HK.00001'] * n,
        'price': [price + i * 0.01 for i in range(n)],
        'volume': [100 + i for i in range(n)],
        'turnover': [0] * n,
        'ticker_direction': ['BUY'] * n,
        'sequence': [start_seq + i for i in range(n)],
        'time': [f'2026-07-03 10:00:{i:02d}' for i in range(n)],
    })


class TestTickerPushPersist(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, 'test_ticker.db')
        conn = sqlite3.connect(self.db_path)
        conn.execute(BusinessTables.TICKER_DATA_TABLE)
        conn.commit()
        conn.close()

        self.db = _FakeDBManager(self.db_path)
        self.handler = TickerPushHandler()
        # 关闭后台 flusher 线程，改由测试手动 flush，保证时序确定
        self.handler._ensure_flusher = lambda: None
        self.handler.set_container(SimpleNamespace(db_manager=self.db))

    def tearDown(self):
        self.db.close()

    def _count_rows(self) -> int:
        conn = sqlite3.connect(self.db_path)
        try:
            return conn.execute('SELECT COUNT(*) FROM ticker_data').fetchone()[0]
        finally:
            conn.close()

    def _trade_dates(self):
        conn = sqlite3.connect(self.db_path)
        try:
            return conn.execute(
                'SELECT DISTINCT trade_date FROM ticker_data ORDER BY trade_date'
            ).fetchall()
        finally:
            conn.close()

    def test_sdk_thread_only_buffers_no_sync_write(self):
        """推送线程入口只进缓冲，不同步写库"""
        self.handler._persist_to_db('HK.00001', _make_df(5))
        self.assertEqual(len(self.handler._db_buffer), 5)
        self.assertEqual(self._count_rows(), 0, 'SDK 线程路径不应有任何落库')

    def test_flush_writes_through_write_queue(self):
        """flush 经写队列批量落库，缓冲清空"""
        self.handler._persist_to_db('HK.00001', _make_df(5))
        self.handler._flush_db_buffer()
        self.assertEqual(self._count_rows(), 5)
        self.assertEqual(len(self.handler._db_buffer), 0)

    def test_trade_date_comes_from_futu_trade_time(self):
        """缓存回放在今天收到，也必须归到真实成交日。"""
        self.handler._persist_to_db('HK.00001', _make_df(2))
        self.handler._flush_db_buffer()
        self.assertEqual(self._trade_dates(), [('2026-07-03',)])

    def test_reflush_is_idempotent(self):
        """同批数据重复 flush 不产生重复行（唯一键 + INSERT OR IGNORE）"""
        df = _make_df(5)
        self.handler._persist_to_db('HK.00001', df)
        self.handler._flush_db_buffer()
        self.handler._persist_to_db('HK.00001', df)  # 模拟断线补发/回放
        self.handler._flush_db_buffer()
        self.assertEqual(self._count_rows(), 5)

    def test_failure_requeues_then_recovers(self):
        """db 不可用时整批塞回缓冲，恢复后重试成功"""
        self.handler.set_container(SimpleNamespace(db_manager=None))
        self.handler._persist_to_db('HK.00001', _make_df(3))
        self.handler._flush_db_buffer()
        self.assertEqual(len(self.handler._db_buffer), 3, '失败批次应塞回缓冲')
        self.assertEqual(self._count_rows(), 0)

        self.handler.set_container(SimpleNamespace(db_manager=self.db))
        self.handler._flush_db_buffer()
        self.assertEqual(self._count_rows(), 3)
        self.assertEqual(len(self.handler._db_buffer), 0)

    def test_buffer_hard_cap_drops_oldest(self):
        """缓冲超硬上限丢最旧，保护内存"""
        self.handler._DB_BUFFER_HARD_CAP = 10
        self.handler._persist_to_db('HK.00001', _make_df(8, start_seq=1))
        self.handler._persist_to_db('HK.00001', _make_df(8, start_seq=100))
        self.assertEqual(len(self.handler._db_buffer), 10)
        # 最旧的（seq 1..6）被丢弃，尾部是最新批
        remaining_seqs = [r[7] for r in self.handler._db_buffer]
        self.assertEqual(remaining_seqs[-1], 107)
        self.assertNotIn(1, remaining_seqs)

    def test_size_trigger_sets_flush_event(self):
        """缓冲到量置位唤醒事件"""
        self.handler._DB_FLUSH_MAX_ROWS = 5
        self.handler._persist_to_db('HK.00001', _make_df(5))
        self.assertTrue(self.handler._db_flush_event.is_set())


if __name__ == '__main__':
    unittest.main()
