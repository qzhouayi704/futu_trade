#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
信号历史管理器

负责：
1. 信号记录存储
2. 信号历史查询
3. 信号去重
4. 信号统计
"""

import logging
from typing import Dict, List, Any
from dataclasses import dataclass, field

from .signal_detector import SignalRecord
from ...database.core.db_manager import DatabaseManager


class SignalHistoryManager:
    """信号历史管理器 - 负责信号的存储和查询"""

    def __init__(
        self,
        db_manager: DatabaseManager,
        max_memory_history: int = 100
    ):
        """
        初始化信号历史管理器

        Args:
            db_manager: 数据库管理器
            max_memory_history: 内存中保留的最大历史记录数
        """
        self.db_manager = db_manager
        self.max_memory_history = max_memory_history

        # 内存中的信号历史（用于快速访问最近的信号）
        self.memory_history: List[SignalRecord] = []

        logging.info(f"信号历史管理器初始化完成，内存历史上限: {max_memory_history}")

    def add_signal(self, signal: Dict[str, Any]):
        """
        添加信号到内存历史记录

        Args:
            signal: 信号字典
        """
        record = SignalRecord(
            stock_code=signal['stock_code'],
            stock_name=signal['stock_name'],
            signal_type=signal['signal_type'],
            price=signal['price'],
            reason=signal['reason'],
            timestamp=signal['timestamp'],
            strategy_id=signal.get('strategy_id', ''),
            preset_name=signal.get('preset_name', ''),
            strategy_data=signal.get('strategy_data', {})
        )

        # 插入到列表开头（最新的在前面）
        self.memory_history.insert(0, record)

        # 限制历史记录数量
        if len(self.memory_history) > self.max_memory_history:
            self.memory_history = self.memory_history[:self.max_memory_history]

    def get_history(
        self,
        limit: int = 50,
        days: int = 7,
        strategy_id: str = None,
        strategy_name: str = None,
        preset_name: str = None
    ) -> List[Dict[str, Any]]:
        """
        获取信号历史 - 从数据库读取，支持查看历史数据

        Args:
            limit: 返回的最大记录数
            days: 查询最近多少天的数据
            strategy_id: 当前策略ID（用于填充缺失的策略信息）
            strategy_name: 当前策略名称
            preset_name: 当前预设名称

        Returns:
            信号列表，按天去重（同一只股票同一天同一类型只返回最新的一条）
        """
        try:
            # 从数据库获取信号历史
            signals = self._get_signals_from_db(
                days=days,
                limit=limit * 3,  # 获取更多以便去重后仍有足够数据
                strategy_id=strategy_id,
                strategy_name=strategy_name,
                preset_name=preset_name
            )

            # 按天去重：同一只股票同一天同一类型信号只保留最新的
            deduplicated = self._deduplicate_signals_by_day(signals)

            return deduplicated[:limit]

        except Exception as e:
            logging.error(f"获取信号历史失败: {e}")
            # 降级到内存历史
            return self._get_memory_history(limit, strategy_name)

    def _get_signals_from_db(
        self,
        days: int = 7,
        limit: int = 200,
        strategy_id: str = None,
        strategy_name: str = None,
        preset_name: str = None
    ) -> List[Dict[str, Any]]:
        """
        从数据库获取信号

        Args:
            days: 查询最近多少天的数据
            limit: 最大记录数
            strategy_id: 当前策略ID
            strategy_name: 当前策略名称
            preset_name: 当前预设名称

        Returns:
            信号列表
        """
        try:
            # 使用小时数来查询
            hours = days * 24
            rows = self.db_manager.trade_history_queries.get_recent_trade_signals(hours=hours, limit=limit)

            signals = []
            for sig in rows:
                signal = {
                    'id': sig.id,
                    'stock_id': sig.stock_id,
                    'signal_type': sig.signal_type,
                    'price': sig.signal_price,
                    'reason': sig.condition_text or '',
                    'timestamp': sig.created_at or '',
                    'stock_code': sig.stock_code or '',
                    'stock_name': sig.stock_name or '',
                    'strategy_id': sig.strategy_id or strategy_id or '',
                    'strategy_name': sig.strategy_name or strategy_name or '低吸高抛策略',
                    'preset_name': preset_name or ''
                }
                signals.append(signal)

            return signals

        except Exception as e:
            logging.error(f"从数据库获取信号失败: {e}")
            return []

    def _deduplicate_signals_by_day(self, signals: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        按天去重信号

        同一只股票同一天同一类型信号只保留最新的一条

        Args:
            signals: 原始信号列表（已按时间倒序）

        Returns:
            去重后的信号列表
        """
        seen = set()  # (date, stock_code, signal_type)
        deduplicated = []

        for signal in signals:
            # 提取日期部分
            timestamp = signal.get('timestamp', '')
            if timestamp:
                # 格式可能是 "2025-01-01 10:30:00" 或 ISO格式
                date_part = timestamp[:10] if len(timestamp) >= 10 else timestamp
            else:
                date_part = ''

            stock_code = signal.get('stock_code', '')
            signal_type = signal.get('signal_type', '')

            key = (date_part, stock_code, signal_type)

            if key not in seen:
                seen.add(key)
                deduplicated.append(signal)

        return deduplicated

    def _get_memory_history(self, limit: int, strategy_name: str = None) -> List[Dict[str, Any]]:
        """
        从内存获取历史记录（降级方案）

        Args:
            limit: 返回的最大记录数
            strategy_name: 策略名称（用于填充缺失的策略信息）

        Returns:
            信号列表
        """
        return [
            {
                'stock_code': r.stock_code,
                'stock_name': r.stock_name,
                'signal_type': r.signal_type,
                'price': r.price,
                'reason': r.reason,
                'timestamp': r.timestamp,
                'strategy_id': r.strategy_id,
                'strategy_name': strategy_name or r.strategy_id or '低吸高抛策略',
                'preset_name': r.preset_name,
                'strategy_data': r.strategy_data
            }
            for r in self.memory_history[:limit]
        ]

    def clear_memory_history(self):
        """清空内存中的信号历史"""
        self.memory_history = []
        logging.info("内存信号历史已清空")

    def get_memory_history_count(self) -> int:
        """获取内存中的历史记录数量"""
        return len(self.memory_history)

    def get_statistics(self, days: int = 7) -> Dict[str, Any]:
        """
        获取信号统计信息

        Args:
            days: 统计最近多少天的数据

        Returns:
            统计信息字典
        """
        try:
            signals = self._get_signals_from_db(days=days, limit=1000)

            total_count = len(signals)
            buy_count = sum(1 for s in signals if s['signal_type'] == 'BUY')
            sell_count = sum(1 for s in signals if s['signal_type'] == 'SELL')

            # 统计每只股票的信号数量
            stock_signal_count = {}
            for signal in signals:
                stock_code = signal['stock_code']
                if stock_code not in stock_signal_count:
                    stock_signal_count[stock_code] = {'buy': 0, 'sell': 0}
                if signal['signal_type'] == 'BUY':
                    stock_signal_count[stock_code]['buy'] += 1
                else:
                    stock_signal_count[stock_code]['sell'] += 1

            return {
                'total_count': total_count,
                'buy_count': buy_count,
                'sell_count': sell_count,
                'stock_count': len(stock_signal_count),
                'memory_history_count': len(self.memory_history),
                'days': days
            }

        except Exception as e:
            logging.error(f"获取信号统计失败: {e}")
            return {
                'total_count': 0,
                'buy_count': 0,
                'sell_count': 0,
                'stock_count': 0,
                'memory_history_count': len(self.memory_history),
                'days': days,
                'error': str(e)
            }
