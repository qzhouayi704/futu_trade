#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PlateNormalizer.fix_historical_data 单元测试"""

import sys
import importlib
import sqlite3
import pytest

# 直接导入模块，绕过 simple_trade.__init__ 的重量级依赖链
spec = importlib.util.spec_from_file_location(
    "plate_normalizer",
    "simple_trade/services/news/plate_normalizer.py"
)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
PlateNormalizer = mod.PlateNormalizer


class FakeDbManager:
    """使用 SQLite 内存数据库模拟 db_manager"""

    def __init__(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.execute("""
            CREATE TABLE news_plates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                news_id INTEGER NOT NULL,
                plate_code VARCHAR(50) NOT NULL,
                plate_name VARCHAR(200),
                impact_type VARCHAR(20),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(news_id, plate_code)
            )
        """)
        self.conn.commit()

    def insert(self, news_id, plate_code, plate_name, impact_type='positive'):
        self.conn.execute(
            "INSERT INTO news_plates (news_id, plate_code, plate_name, impact_type) VALUES (?, ?, ?, ?)",
            (news_id, plate_code, plate_name, impact_type)
        )
        self.conn.commit()

    def execute_query(self, sql, params=None):
        cursor = self.conn.execute(sql, params or ())
        return cursor.fetchall()

    def execute_update(self, sql, params=None):
        cursor = self.conn.execute(sql, params or ())
        self.conn.commit()
        return cursor.rowcount


class TestFixHistoricalData:
    """fix_historical_data 方法测试"""

    def setup_method(self):
        self.normalizer = PlateNormalizer()
        self.db = FakeDbManager()

    def test_empty_table(self):
        """空表应返回全零统计"""
        stats = self.normalizer.fix_historical_data(self.db)
        assert stats == {'scanned': 0, 'updated': 0, 'merged': 0}

    def test_no_changes_needed(self):
        """已标准化的记录不应被修改"""
        self.db.insert(1, '科技', '科技')
        self.db.insert(2, '未知板块', '未知板块')

        stats = self.normalizer.fix_historical_data(self.db)
        assert stats['scanned'] == 2
        assert stats['updated'] == 0
        assert stats['merged'] == 0

    def test_update_non_standard(self):
        """非标准名称应被更新为标准值"""
        self.db.insert(1, 'AI', '人工智能')
        self.db.insert(2, '电动车', '电动车')

        stats = self.normalizer.fix_historical_data(self.db)
        assert stats['updated'] == 2
        assert stats['merged'] == 0

        # 验证数据库中的值已更新
        rows = self.db.execute_query("SELECT plate_code, plate_name FROM news_plates ORDER BY id")
        assert rows[0] == ('科技', '科技')
        assert rows[1] == ('新能源', '新能源')

    def test_merge_duplicates(self):
        """同一 news_id 下标准化后 plate_code 重复时，应合并（删除多余记录）"""
        # news_id=1 下有 'AI' 和 '科技'，标准化后都是 '科技'
        self.db.insert(1, '科技', '科技')
        self.db.insert(1, 'AI', '人工智能')

        stats = self.normalizer.fix_historical_data(self.db)
        assert stats['merged'] == 1

        # 应只剩一条记录
        rows = self.db.execute_query("SELECT plate_code, plate_name FROM news_plates WHERE news_id = 1")
        assert len(rows) == 1
        assert rows[0] == ('科技', '科技')

    def test_mixed_update_and_merge(self):
        """混合场景：部分更新、部分合并"""
        # news_id=1: '芯片' 和 '半导体' 都映射到 '科技'，需要合并
        self.db.insert(1, '芯片', '芯片')
        self.db.insert(1, '半导体', '半导体')
        # news_id=2: '电动车' 映射到 '新能源'，无冲突，只需更新
        self.db.insert(2, '电动车', '电动车')

        stats = self.normalizer.fix_historical_data(self.db)
        assert stats['scanned'] == 3
        # '芯片' 先被更新为 '科技'，'半导体' 发现冲突被合并
        assert stats['updated'] + stats['merged'] >= 2

        # news_id=1 应只剩一条 '科技'
        rows = self.db.execute_query("SELECT plate_code FROM news_plates WHERE news_id = 1")
        assert len(rows) == 1
        assert rows[0][0] == '科技'

    def test_traditional_chinese_normalization(self):
        """繁体中文别名应被正确标准化"""
        self.db.insert(1, '互聯網', '互聯網')
        self.db.insert(2, '醫藥', '醫藥')

        stats = self.normalizer.fix_historical_data(self.db)
        assert stats['updated'] == 2

        rows = self.db.execute_query("SELECT plate_code, plate_name FROM news_plates ORDER BY id")
        assert rows[0] == ('科技', '科技')
        assert rows[1] == ('医药', '医药')

    def test_returns_correct_stats(self):
        """统计信息应准确反映操作结果"""
        self.db.insert(1, '未知', '未知')       # 不变
        self.db.insert(2, '银行', '银行')       # 更新
        self.db.insert(3, '科技', '科技')       # 不变
        self.db.insert(3, 'AI', '人工智能')     # 合并（news_id=3 已有 '科技'）

        stats = self.normalizer.fix_historical_data(self.db)
        assert stats['scanned'] == 4
        assert stats['updated'] == 1   # '银行' → '金融'
        assert stats['merged'] == 1    # 'AI' 与 '科技' 合并
