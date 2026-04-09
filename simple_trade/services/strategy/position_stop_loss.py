#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
持仓止损检查器

从 ScreeningEngine 中提取的通用止损逻辑，不依赖特定策略。
检查持仓股票是否触发「趋势未延续止损」。
"""

import logging
from dataclasses import dataclass
from typing import Dict, Any, Optional, List

from ...database.core.db_manager import DatabaseManager


@dataclass
class StopLossParams:
    """止损检查参数"""
    min_rise_pct: float = 5.0     # 最低涨幅要求 (%)
    check_days: int = 3           # 连续低涨幅天数阈值


class PositionStopLossChecker:
    """
    持仓止损检查器

    检查持仓股票是否触发趋势未延续止损：
    1. 优先使用富途持仓的成本价信息
    2. 降级：从交易记录获取买入日期
    3. 降级：通过12日低点识别买入日
    4. 降级：使用K线起始日期作为假设买入日
    5. 从买入日/成本价开始检查，如果连续N天最高价涨幅<M%，则触发止损
    """

    def __init__(self, db_manager: DatabaseManager,
                 params: StopLossParams = None):
        self.db_manager = db_manager
        self.params = params or StopLossParams()

    def check(
        self,
        stock_code: str,
        quote: Dict[str, Any],
        position_info: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """检查持仓股票是否触发趋势未延续止损"""
        result = self._empty_result()

        try:
            # 优先使用富途持仓的成本价信息
            if position_info and position_info.get('cost_price', 0) > 0:
                return self._check_by_cost_price(
                    stock_code, quote, position_info, result
                )

            # 降级方案：使用K线数据推断买入日
            logging.debug(f"{stock_code} 未获取到富途持仓成本价，使用降级方案")
            return self._check_by_kline_fallback(stock_code, result)

        except Exception as e:
            logging.error(f"检查持仓止损失败 {stock_code}: {e}")
            result['reason'] = f'检查异常: {str(e)}'
            return result

    @staticmethod
    def _empty_result() -> Dict[str, Any]:
        return {
            'should_stop_loss': False, 'reason': '',
            'buy_date': None, 'buy_date_high': 0, 'cost_price': 0,
            'days_held': 0, 'max_rise_pct': 0,
            'consecutive_low_rise_days': 0, 'buy_source': '',
        }

    def _check_by_cost_price(
        self, stock_code: str, quote: Dict[str, Any],
        position_info: Dict[str, Any], result: Dict[str, Any],
    ) -> Dict[str, Any]:
        """使用富途持仓成本价检查止损"""
        cost_price = position_info['cost_price']
        current_price = quote.get('last_price', 0)
        result['cost_price'] = cost_price
        result['buy_source'] = '富途持仓成本价'

        if current_price <= 0:
            result['reason'] = '当前价格无效'
            return result

        klines = self.db_manager.kline_queries.get_stock_kline(stock_code, days=10)
        if len(klines) < self.params.check_days:
            result['reason'] = f'K线数据不足（{len(klines)}天）'
            return result

        consecutive, max_rise = self._count_consecutive_low_rise(
            klines[-self.params.check_days:], cost_price
        )
        result['max_rise_pct'] = round(max_rise, 2)
        result['consecutive_low_rise_days'] = consecutive
        result['days_held'] = len(klines)

        if consecutive >= self.params.check_days:
            result['should_stop_loss'] = True
            result['reason'] = (
                f"[!] 趋势未延续止损: 连续{consecutive}天最高价涨幅"
                f"<{self.params.min_rise_pct}%, 最高涨幅仅{max_rise:.1f}%, "
                f"成本价{cost_price:.2f}, 现价{current_price:.2f} "
                f"(数据来源:富途持仓)"
            )
            logging.warning(f"{stock_code} 触发趋势未延续止损: {result['reason']}")
        else:
            result['reason'] = (
                f"连续{consecutive}天低涨幅（需{self.params.check_days}天触发），"
                f"成本价{cost_price:.2f}, 数据来源:富途持仓"
            )
        return result

    def _check_by_kline_fallback(
        self, stock_code: str, result: Dict[str, Any],
    ) -> Dict[str, Any]:
        """降级方案：通过K线数据推断买入日并检查止损"""
        klines = self.db_manager.kline_queries.get_stock_kline(stock_code, days=30)
        if len(klines) < 3:
            result['reason'] = f'K线数据不足（{len(klines)}天）'
            return result

        buy_date_idx, buy_date_high, buy_source = self._find_buy_date(
            stock_code, klines
        )
        if buy_date_idx is None:
            result['reason'] = '无法确定买入日期'
            return result

        result['buy_date'] = klines[buy_date_idx]['date']
        result['buy_date_high'] = buy_date_high
        result['buy_source'] = buy_source

        klines_after_buy = klines[buy_date_idx + 1:]
        result['days_held'] = len(klines_after_buy)

        if len(klines_after_buy) < self.params.check_days:
            result['reason'] = (
                f'持有时间不足{self.params.check_days}天'
                f'（仅{len(klines_after_buy)}天）'
            )
            return result

        consecutive, max_rise = self._count_consecutive_low_rise(
            klines_after_buy, buy_date_high
        )
        result['max_rise_pct'] = round(max_rise, 2)
        result['consecutive_low_rise_days'] = consecutive

        if consecutive >= self.params.check_days:
            result['should_stop_loss'] = True
            result['reason'] = (
                f"[!] 趋势未延续止损: 买入后连续{consecutive}天最高价涨幅"
                f"<{self.params.min_rise_pct}%, 最高涨幅仅{max_rise:.1f}%, "
                f"持有{result['days_held']}天 (买入日来源:{buy_source})"
            )
            logging.warning(f"{stock_code} 触发趋势未延续止损: {result['reason']}")
        else:
            result['reason'] = (
                f"持有{result['days_held']}天，连续{consecutive}天低涨幅"
                f"（需{self.params.check_days}天触发），买入日来源:{buy_source}"
            )
        return result

    def _count_consecutive_low_rise(
        self, klines: List[Dict], base_price: float,
    ) -> tuple:
        """计算连续低涨幅天数和最大涨幅"""
        consecutive = 0
        max_rise = 0.0
        for day in klines:
            day_high = day['high']
            if day_high > 0 and base_price > 0:
                rise_pct = ((day_high - base_price) / base_price) * 100
                max_rise = max(max_rise, rise_pct)
                if rise_pct < self.params.min_rise_pct:
                    consecutive += 1
                else:
                    consecutive = 0
        return consecutive, max_rise

    def _find_buy_date(
        self, stock_code: str, klines: List[Dict],
    ) -> tuple:
        """推断买入日期，返回 (index, high_price, source)"""
        # 步骤1：从交易记录获取
        buy_record = self._get_buy_record_from_db(stock_code)
        if buy_record and buy_record.get('date'):
            for i, k in enumerate(klines):
                if k['date'] and buy_record['date'] in k['date']:
                    return i, buy_record.get('high') or k['high'], '交易记录'

        # 步骤2：通过12日低点识别
        if len(klines) >= 12:
            for i in range(1, len(klines) - 1):
                yesterday = klines[i]
                today = klines[i + 1] if i + 1 < len(klines) else None
                if not today:
                    continue
                start_idx = max(0, i - 11)
                lows_12d = [k['low'] for k in klines[start_idx:i + 1]]
                min_low_12d = min(lows_12d)
                if yesterday['low'] == min_low_12d and today['low'] > yesterday['low']:
                    return i + 1, today['high'], '12日低点'

        # 步骤3：使用K线起始日期
        if len(klines) >= self.params.check_days + 1:
            logging.info(f"{stock_code} 未找到买入信号点，使用K线起始日期")
            return 0, klines[0]['high'], 'K线起始日(假设)'

        return None, 0, ''

    def _get_buy_record_from_db(self, stock_code: str) -> Optional[Dict[str, Any]]:
        """从数据库获取最近的买入记录"""
        try:
            result = self.db_manager.execute_query('''
                SELECT ts.created_at, k.high_price
                FROM trade_signals ts
                INNER JOIN stocks s ON ts.stock_id = s.id
                LEFT JOIN kline_data k ON k.stock_code = s.code
                    AND DATE(k.time_key) = DATE(ts.created_at)
                WHERE s.code = ?
                AND ts.signal_type = 'BUY'
                AND ts.is_executed = 1
                AND ts.created_at >= DATE('now', '-30 days')
                ORDER BY ts.created_at DESC
                LIMIT 1
            ''', (stock_code,))

            if result and result[0]:
                return {'date': result[0][0], 'high': result[0][1] or 0}
        except Exception as e:
            logging.debug(f"获取买入记录失败 {stock_code}: {e}")
        return None