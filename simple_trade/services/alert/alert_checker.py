#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
预警检查模块

负责各类预警条件的检查和判断，包括涨跌幅预警、成交量异常预警、
价格突破预警等。同时提供交易条件显示、预警统计等辅助功能。

从 alert_service.py 拆分而来。
"""

import logging
from datetime import datetime
from typing import List, Dict, Any
from ...database.core.db_manager import DatabaseManager
from ...config.config import Config
from .price_change_tracker import PriceChangeTracker, PriceChangeConfig


class AlertChecker:
    """预警检查器

    负责：
    - 涨跌幅预警检查
    - 成交量异常预警
    - 价格突破预警（接近日高/日低）
    - 交易条件滚动显示
    - 预警统计和过滤
    """

    def __init__(self, db_manager: DatabaseManager, config: Config):
        self.db_manager = db_manager
        self.config = config

        # 初始化价格变动追踪器
        price_config = PriceChangeConfig(
            rise_threshold=getattr(config, 'alert_5min_rise_threshold', 2.0),
            fall_threshold=getattr(config, 'alert_5min_fall_threshold', 3.0),
            amplitude_threshold=getattr(
                config, 'alert_5min_amplitude_threshold', 5.0
            ),
            history_duration=getattr(config, 'price_history_duration', 300),
        )
        self.price_tracker = PriceChangeTracker(price_config)

        # 预警缓存：{stock_code:alert_type: {last_trigger_time, last_percent}}
        self.alert_cache: Dict[str, Dict[str, Any]] = {}

        # 冷却期（秒）
        self.cooldown_seconds = getattr(config, 'alert_cooldown_seconds', 300)

        # 涨跌幅增量阈值（百分比）
        self.percent_increment_threshold = getattr(
            config, 'alert_percent_increment_threshold', 1.0
        )

        # 日内振幅最小阈值（百分比），低于此值跳过价格突破预警
        self.min_breakout_amplitude = getattr(
            config, 'min_breakout_amplitude', 1.0
        )

        # 上次清理缓存的时间
        self.last_cleanup_time = datetime.now()

    def check_alerts(self, quotes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """检查交易预警"""
        all_alerts = []

        # 定期清理过期缓存（每分钟一次）
        current_time = datetime.now()
        if (current_time - self.last_cleanup_time).total_seconds() > 60:
            self._cleanup_expired_cache()
            self.last_cleanup_time = current_time

        for quote in quotes:
            try:
                stock_code = quote.get('code', '')
                if not stock_code:
                    continue

                # 跟踪价格历史
                self.price_tracker.track_price(quote)

                # 收集所有预警
                alerts = []

                # 5分钟内价格变化预警
                self.price_tracker.check_5min_price_change(quote, alerts)

                # 涨跌幅预警
                self._check_price_change(quote, alerts)

                # 成交量异常预警
                self._check_volume_anomaly(quote, alerts)

                # 价格突破预警
                self._check_price_breakout(quote, alerts)

                # 智能过滤（混合方案）
                filtered_alerts = self._filter_alerts_with_hybrid_logic(
                    alerts, stock_code
                )
                all_alerts.extend(filtered_alerts)

            except Exception as e:
                logging.error(f"处理预警检查失败 {quote['code']}: {e}")

        # 清理过期的价格历史数据
        self.price_tracker.clean_old_history()

        # 按股票聚合日志输出（替代逐条 INFO）
        self._log_aggregated_alerts(all_alerts)

        return all_alerts

    def _check_price_change(
        self, quote: Dict[str, Any], alerts: List[Dict[str, Any]]
    ):
        """检查涨跌幅预警"""
        change_pct = quote['change_percent']
        if abs(change_pct) >= self.config.price_change_threshold:
            alert_type = "涨幅预警" if change_pct > 0 else "跌幅预警"
            alerts.append({
                'type': alert_type,
                'stock_code': quote['code'],
                'stock_name': quote['name'],
                'current_price': quote['current_price'],
                'change_percent': change_pct,
                'message': (
                    f"{quote['name']}({quote['code']}) "
                    f"{alert_type}: {change_pct:.2f}%"
                ),
                'timestamp': datetime.now().isoformat(),
                'level': 'warning' if abs(change_pct) < 5 else 'danger',
            })

    def _check_volume_anomaly(
        self, quote: Dict[str, Any], alerts: List[Dict[str, Any]]
    ):
        """检查成交量异常预警"""
        if quote['volume'] > 5000000:  # 成交量超过500万
            volume = quote['volume']
            volume_display = self._format_volume(volume)
            alerts.append({
                'type': '成交量异常',
                'stock_code': quote['code'],
                'stock_name': quote['name'],
                'volume': volume,
                'volume_display': volume_display,
                'message': (
                    f"{quote['name']}({quote['code']}) "
                    f"成交量异常: {volume_display}"
                ),
                'timestamp': datetime.now().isoformat(),
                'level': 'info',
            })
    @staticmethod
    def _format_volume(volume: int) -> str:
        """将成交量格式化为易读的中文单位（百万/万）"""
        if volume >= 100_000_000:
            return f"{volume / 100_000_000:.1f}亿"
        if volume >= 1_000_000:
            return f"{volume / 1_000_000:.1f}百万"
        if volume >= 10_000:
            return f"{volume / 10_000:.1f}万"
        return f"{volume:,}"

    def _check_price_breakout(
        self, quote: Dict[str, Any], alerts: List[Dict[str, Any]]
    ):
        """检查价格突破预警"""
        try:
            current_price = quote.get('current_price', 0)
            high_price = quote.get('high_price', 0)
            low_price = quote.get('low_price', 0)

            # 日内振幅过小时跳过价格突破检查
            if low_price > 0 and high_price > 0:
                amplitude = (high_price - low_price) / low_price * 100
                if amplitude < self.min_breakout_amplitude:
                    return

            # 接近日内最高价
            if current_price > 0 and high_price > 0:
                high_ratio = current_price / high_price
                if high_ratio >= 0.98:
                    alerts.append({
                        'type': '接近日高',
                        'stock_code': quote['code'],
                        'stock_name': quote['name'],
                        'current_price': current_price,
                        'high_price': high_price,
                        'message': (
                            f"{quote['name']}({quote['code']}) "
                            f"接近日内最高价: {current_price:.2f}"
                        ),
                        'timestamp': datetime.now().isoformat(),
                        'level': 'info',
                    })

            # 接近日内最低价
            if current_price > 0 and low_price > 0:
                low_ratio = current_price / low_price
                if low_ratio <= 1.02:
                    alerts.append({
                        'type': '接近日低',
                        'stock_code': quote['code'],
                        'stock_name': quote['name'],
                        'current_price': current_price,
                        'low_price': low_price,
                        'message': (
                            f"{quote['name']}({quote['code']}) "
                            f"接近日内最低价: {current_price:.2f}"
                        ),
                        'timestamp': datetime.now().isoformat(),
                        'level': 'warning',
                    })

        except Exception as e:
            logging.error(f"检查价格突破失败 {quote['code']}: {e}")

    def get_conditions_display(self) -> List[Dict[str, Any]]:
        """获取交易条件滚动显示"""
        conditions = []

        try:
            signals = (
                self.db_manager.trade_history_queries
                .get_recent_trade_signals(
                    hours=24, limit=self.config.max_recent_signals
                )
            )

            for signal in signals:
                condition_text = f"{signal.stock_name}({signal.stock_code}) "
                if signal.signal_type == 'BUY':
                    condition_text += f"买入信号触发 - 价格: {signal.signal_price:.2f}"
                else:
                    condition_text += f"卖出信号触发 - 价格: {signal.signal_price:.2f}"

                conditions.append({
                    'id': signal.id,
                    'stock_code': signal.stock_code,
                    'stock_name': signal.stock_name,
                    'signal_type': signal.signal_type,
                    'condition_text': condition_text,
                    'timestamp': signal.created_at,
                    'is_executed': signal.is_executed,
                })

        except Exception as e:
            logging.error(f"获取交易条件失败: {e}")

        return conditions

    def create_custom_alert(
        self, stock_code: str, alert_type: str,
        threshold: float, message: str
    ) -> bool:
        """创建自定义预警"""
        try:
            logging.info(
                f"创建自定义预警: {stock_code} - {alert_type} "
                f"- {threshold} - {message}"
            )
            return True
        except Exception as e:
            logging.error(f"创建自定义预警失败: {e}")
            return False

    def get_alert_history(self, hours: int = 24) -> List[Dict[str, Any]]:
        """获取预警历史（可扩展功能）"""
        return []

    def filter_alerts_by_level(
        self, alerts: List[Dict[str, Any]], level: str
    ) -> List[Dict[str, Any]]:
        """按级别过滤预警"""
        return [alert for alert in alerts if alert.get('level') == level]

    def get_alert_statistics(
        self, alerts: List[Dict[str, Any]]
    ) -> Dict[str, int]:
        """获取预警统计信息"""
        stats = {
            'total': len(alerts),
            'danger': 0,
            'warning': 0,
            'info': 0,
            'price_alerts': 0,
            'volume_alerts': 0,
            'breakout_alerts': 0,
        }

        for alert in alerts:
            level = alert.get('level', 'info')
            if level in stats:
                stats[level] += 1

            alert_type = alert.get('type', '')
            if '涨幅预警' in alert_type or '跌幅预警' in alert_type:
                stats['price_alerts'] += 1
            elif '成交量异常' in alert_type:
                stats['volume_alerts'] += 1
            elif '接近日高' in alert_type or '接近日低' in alert_type:
                stats['breakout_alerts'] += 1

        return stats

    def get_price_history_stats(self) -> Dict[str, Any]:
        """获取价格历史缓存统计（委托给 price_tracker）"""
        return self.price_tracker.get_stats()

    def _filter_alerts_with_hybrid_logic(
        self, alerts: List[Dict[str, Any]], stock_code: str
    ) -> List[Dict[str, Any]]:
        """使用混合方案过滤预警（冷却期 + 幅度增量）"""
        filtered = []

        for alert in alerts:
            alert_type = alert['type']

            # 获取当前涨跌幅
            current_percent = self._get_alert_percent(alert)

            # 判断是否应该触发
            if self._should_trigger_alert(stock_code, alert_type, current_percent):
                filtered.append(alert)
                # 更新缓存
                self._update_alert_cache(stock_code, alert_type, current_percent)
                logging.debug(f"预警触发: {alert['message']}")

        return filtered
    def _log_aggregated_alerts(self, alerts: List[Dict[str, Any]]):
        """按股票聚合预警日志输出"""
        if not alerts:
            return

        # 按 stock_code 分组
        grouped: Dict[str, List[Dict]] = {}
        for alert in alerts:
            code = alert['stock_code']
            grouped.setdefault(code, []).append(alert)

        for code, stock_alerts in grouped.items():
            if len(stock_alerts) == 1:
                logging.info(f"预警触发: {stock_alerts[0]['message']}")
            else:
                name = stock_alerts[0]['stock_name']
                types = ', '.join(a['type'] for a in stock_alerts)
                logging.info(
                    f"预警触发: {name}({code}) "
                    f"共{len(stock_alerts)}条 [{types}]"
                )

    def _get_alert_percent(self, alert: Dict[str, Any]) -> float:
        """从预警对象中提取涨跌幅百分比"""
        if 'rise_percent' in alert and alert['rise_percent'] is not None:
            return alert['rise_percent']
        elif 'fall_percent' in alert and alert['fall_percent'] is not None:
            return abs(alert['fall_percent'])  # 跌幅取绝对值
        elif 'amplitude' in alert:
            return alert['amplitude']
        elif 'change_percent' in alert:
            return abs(alert['change_percent'])
        return 0.0

    def _should_trigger_alert(
        self, stock_code: str, alert_type: str, current_percent: float
    ) -> bool:
        """判断是否应该触发预警（混合方案）"""
        cache_key = f"{stock_code}:{alert_type}"
        current_time = datetime.now()

        if cache_key not in self.alert_cache:
            # 首次触发
            return True

        cache_data = self.alert_cache[cache_key]
        last_trigger_time = cache_data["last_trigger_time"]
        last_percent = cache_data["last_percent"]

        time_diff = (current_time - last_trigger_time).total_seconds()

        if time_diff < self.cooldown_seconds:
            # 在冷却期内，检查涨幅增量
            percent_diff = abs(current_percent - last_percent)
            if percent_diff >= self.percent_increment_threshold:
                # 涨幅增加超过阈值，触发
                logging.debug(
                    f"预警触发（增量）: {stock_code} {alert_type} "
                    f"涨幅增量 {percent_diff:.2f}% >= {self.percent_increment_threshold}%"
                )
                return True
            else:
                # 涨幅增加不足，不触发
                logging.debug(
                    f"预警去重: {stock_code} {alert_type} 涨幅增量不足 "
                    f"({percent_diff:.2f}% < {self.percent_increment_threshold}%)"
                )
                return False
        else:
            # 超过冷却期，可以触发
            logging.debug(
                f"预警触发（冷却期结束）: {stock_code} {alert_type} "
                f"距上次 {time_diff:.0f}秒"
            )
            return True

    def _update_alert_cache(
        self, stock_code: str, alert_type: str, current_percent: float
    ):
        """更新预警缓存"""
        cache_key = f"{stock_code}:{alert_type}"
        self.alert_cache[cache_key] = {
            "last_trigger_time": datetime.now(),
            "last_percent": current_percent
        }

    def _cleanup_expired_cache(self):
        """清理过期的预警缓存"""
        current_time = datetime.now()
        expired_keys = []

        for cache_key, cache_data in self.alert_cache.items():
            last_trigger_time = cache_data["last_trigger_time"]
            time_diff = (current_time - last_trigger_time).total_seconds()

            # 超过2倍冷却期的缓存可以清理
            if time_diff > self.cooldown_seconds * 2:
                expired_keys.append(cache_key)

        for key in expired_keys:
            del self.alert_cache[key]

        if expired_keys:
            logging.debug(f"清理过期预警缓存: {len(expired_keys)} 条")
