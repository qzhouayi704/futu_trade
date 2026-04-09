#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
价格变动追踪模块

负责跟踪股票价格历史、检测短时间内的价格异常变动（如5分钟涨跌幅/振幅预警），
以及清理过期的价格历史数据。

从 alert_service.py 拆分而来。
"""

import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any
from collections import defaultdict, deque
from dataclasses import dataclass, field

from ...utils.converters import get_last_price


@dataclass
class PriceChangeConfig:
    """价格变动追踪配置"""
    rise_threshold: float = 2.0       # 5分钟涨幅预警阈值(%)
    fall_threshold: float = 3.0       # 5分钟跌幅预警阈值(%)
    amplitude_threshold: float = 5.0  # 5分钟振幅预警阈值(%)
    history_duration: int = 300       # 价格历史保留时长(秒)
    history_maxlen: int = 100         # 每只股票最大价格记录数


class PriceChangeTracker:
    """价格变动追踪器

    负责：
    - 跟踪每只股票的实时价格历史
    - 检测5分钟内的涨跌幅和振幅异常
    - 清理过期的价格历史数据
    - 提供价格历史缓存统计
    """

    def __init__(self, config: PriceChangeConfig):
        self.config = config
        # 价格历史缓存: {stock_code: deque([(price, timestamp), ...], maxlen)}
        self.price_history: Dict[str, deque] = defaultdict(
            lambda: deque(maxlen=self.config.history_maxlen)
        )

    def track_price(self, quote: Dict[str, Any]):
        """跟踪股票价格历史"""
        try:
            stock_code = quote.get('code', '')
            current_price = get_last_price(quote)

            if stock_code and current_price > 0:
                current_time = datetime.now()
                self.price_history[stock_code].append((current_price, current_time))

        except Exception as e:
            logging.error(f"跟踪价格历史失败 {quote.get('code', 'unknown')}: {e}")

    def check_5min_price_change(self, quote: Dict[str, Any], alerts: List[Dict[str, Any]]):
        """检查5分钟内的价格变化预警 - 基于最高/最低价计算涨跌幅"""
        try:
            stock_code = quote.get('code', '')
            stock_name = quote.get('name', quote.get('stock_name', ''))
            current_price = get_last_price(quote)

            if not stock_code or current_price <= 0:
                return

            price_history = self.price_history[stock_code]
            if len(price_history) < 2:
                return

            current_time = datetime.now()
            cutoff_time = current_time - timedelta(seconds=self.config.history_duration)

            # 获取5分钟内的有效数据并按时间排序
            valid_data = sorted(
                [(price, ts) for price, ts in price_history if ts >= cutoff_time],
                key=lambda x: x[1]
            )

            if len(valid_data) < 2:
                return

            five_min_prices = [price for price, _ in valid_data]
            base_price = valid_data[0][0]  # 最早的价格作为基准

            if base_price <= 0:
                return

            max_price = max(five_min_prices)
            min_price = min(five_min_prices)

            # 计算涨跌幅和振幅
            rise_percent = ((max_price - base_price) / base_price) * 100
            fall_percent = ((min_price - base_price) / base_price) * 100
            amplitude = ((max_price - min_price) / min_price) * 100 if min_price > 0 else 0

            alerts_generated = self._generate_5min_alerts(
                stock_code, stock_name, current_price, base_price,
                max_price, min_price, rise_percent, fall_percent,
                amplitude, current_time
            )

            alerts.extend(alerts_generated)

            if alerts_generated:
                for alert in alerts_generated:
                    logging.debug(
                        f"5分钟预警候选: {stock_name}({stock_code}) "
                        f"{alert['type']} - {alert['message']}"
                    )

        except Exception as e:
            logging.error(f"检查5分钟价格变化失败 {quote.get('code', 'unknown')}: {e}")

    def _generate_5min_alerts(
        self, stock_code: str, stock_name: str, current_price: float,
        base_price: float, max_price: float, min_price: float,
        rise_percent: float, fall_percent: float, amplitude: float,
        current_time: datetime
    ) -> List[Dict[str, Any]]:
        """根据涨跌幅和振幅生成5分钟预警"""
        alerts = []
        common = {
            'stock_code': stock_code,
            'stock_name': stock_name,
            'current_price': current_price,
            'base_price': base_price,
            'max_price': max_price,
            'min_price': min_price,
            'amplitude': round(amplitude, 2),
            'timestamp': current_time.isoformat(),
            'time_period': '5分钟',
        }

        # 涨幅预警
        if rise_percent > self.config.rise_threshold:
            alerts.append({
                **common,
                'type': '5分钟涨幅预警',
                'rise_percent': round(rise_percent, 2),
                'message': (
                    f"{stock_name}({stock_code}) 5分钟涨幅预警: "
                    f"基准价 {base_price:.2f} → 最高价 {max_price:.2f} "
                    f"(+{rise_percent:.2f}%) 振幅: {amplitude:.2f}%"
                ),
                'level': 'danger' if rise_percent > 5.0 else 'warning',
            })

        # 跌幅预警
        if fall_percent < -self.config.fall_threshold:
            alerts.append({
                **common,
                'type': '5分钟跌幅预警',
                'fall_percent': round(fall_percent, 2),
                'message': (
                    f"{stock_name}({stock_code}) 5分钟跌幅预警: "
                    f"基准价 {base_price:.2f} → 最低价 {min_price:.2f} "
                    f"({fall_percent:.2f}%) 振幅: {amplitude:.2f}%"
                ),
                'level': 'danger' if abs(fall_percent) > 5.0 else 'warning',
            })

        # 振幅预警
        if amplitude > self.config.amplitude_threshold:
            alerts.append({
                **common,
                'type': '5分钟振幅预警',
                'message': (
                    f"{stock_name}({stock_code}) 5分钟振幅预警: "
                    f"振幅 {amplitude:.2f}% "
                    f"(最高 {max_price:.2f}, 最低 {min_price:.2f})"
                ),
                'level': 'info' if amplitude < 8.0 else 'warning',
            })

        return alerts

    def clean_old_history(self):
        """清理过期的价格历史数据"""
        try:
            current_time = datetime.now()
            # 保留2倍时长的数据
            cutoff_time = current_time - timedelta(
                seconds=self.config.history_duration * 2
            )

            cleaned_stocks = []
            for stock_code, history in self.price_history.items():
                original_len = len(history)
                while history and history[0][1] < cutoff_time:
                    history.popleft()
                if len(history) < original_len:
                    cleaned_stocks.append(
                        (stock_code, original_len - len(history))
                    )

            if cleaned_stocks:
                total_cleaned = sum(count for _, count in cleaned_stocks)
                logging.debug(
                    f"清理了{len(cleaned_stocks)}只股票的过期价格历史，"
                    f"共{total_cleaned}条记录"
                )

            # 清理空的历史记录
            empty_stocks = [
                code for code, history in self.price_history.items()
                if not history
            ]
            for code in empty_stocks:
                del self.price_history[code]

            if empty_stocks:
                logging.debug(f"清理了{len(empty_stocks)}只股票的空历史记录")

        except Exception as e:
            logging.error(f"清理价格历史数据失败: {e}")

    def get_stats(self) -> Dict[str, Any]:
        """获取价格历史缓存统计信息"""
        try:
            total_stocks = len(self.price_history)
            total_records = sum(
                len(history) for history in self.price_history.values()
            )
            avg_records = total_records / total_stocks if total_stocks > 0 else 0

            current_time = datetime.now()
            recent_counts = {'1min': 0, '5min': 0, '10min': 0}

            for history in self.price_history.values():
                for _price, timestamp in history:
                    time_diff = (current_time - timestamp).total_seconds()
                    if time_diff <= 60:
                        recent_counts['1min'] += 1
                    if time_diff <= 300:
                        recent_counts['5min'] += 1
                    if time_diff <= 600:
                        recent_counts['10min'] += 1

            return {
                'total_stocks': total_stocks,
                'total_records': total_records,
                'avg_records_per_stock': round(avg_records, 1),
                'recent_records': recent_counts,
                'cache_duration_seconds': self.config.history_duration,
                'alert_thresholds': {
                    'rise': f'{self.config.rise_threshold}%',
                    'fall': f'{self.config.fall_threshold}%',
                    'amplitude': f'{self.config.amplitude_threshold}%',
                },
            }

        except Exception as e:
            logging.error(f"获取价格历史统计失败: {e}")
            return {}
