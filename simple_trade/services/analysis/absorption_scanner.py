#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
买入吸收异常扫描器

定期扫描所有已订阅股票的逐笔数据，检测"持续主买但价格不涨"的压单吸收模式。
由 QuotePipeline 的监控周期调用，通过 WebSocket 推送实时预警。
"""

import logging
from collections import defaultdict
from datetime import date, datetime
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class AbsorptionScanner:
    """买入吸收异常实时扫描器"""

    # 检测参数
    MIN_WINDOW = 5          # 最少连续5分钟净买入
    PRICE_THRESHOLD = 0.1   # 价格涨幅阈值 ≤0.1% 视为"不涨"
    COOLDOWN_MINUTES = 15   # 同一只股票报警后冷却时间（分钟）

    def __init__(self, db_manager):
        self._db = db_manager
        # 冷却记录: {stock_code: last_alert_time}
        self._cooldown: Dict[str, datetime] = {}

    def scan_all(self, stock_codes: List[str]) -> List[Dict]:
        """扫描所有给定股票，返回检测到的吸收预警列表

        Args:
            stock_codes: 要扫描的股票代码列表

        Returns:
            list of alert dicts, each containing:
                stock_code, stock_name, severity, message, details...
        """
        if not stock_codes or not self._db:
            return []

        today_str = date.today().isoformat()
        alerts = []

        # 批量查询所有股票的分钟级聚合数据（单次 SQL 查询）
        try:
            placeholders = ','.join(['?' for _ in stock_codes])
            rows = self._db.execute_query(f"""
                SELECT
                    stock_code,
                    substr(datetime(timestamp/1000, 'unixepoch', '+8 hours'), 12, 5) as minute,
                    direction,
                    SUM(turnover) as total_turnover,
                    SUM(volume) as total_volume,
                    AVG(price) as avg_price
                FROM ticker_data
                WHERE stock_code IN ({placeholders}) AND trade_date = ?
                GROUP BY stock_code, minute, direction
                ORDER BY stock_code, minute
            """, (*stock_codes, today_str))
        except Exception as e:
            logger.debug(f"[吸收扫描] 查询 ticker_data 失败: {e}")
            return []

        if not rows:
            return []

        # 按股票分组构建时间线
        stock_minutes: Dict[str, Dict] = defaultdict(
            lambda: defaultdict(lambda: {'buy': 0.0, 'sell': 0.0, 'price_sum': 0.0, 'price_n': 0})
        )

        for row in rows:
            code, minute, direction, turnover, volume, avg_price = row
            # 交易时段过滤
            if not ('09:15' <= (minute or '') <= '16:10'):
                continue
            entry = stock_minutes[code][minute]
            tv = float(turnover or 0)
            if direction == 'BUY':
                entry['buy'] += tv
            elif direction == 'SELL':
                entry['sell'] += tv
            if avg_price and float(avg_price) > 0:
                entry['price_sum'] += float(avg_price)
                entry['price_n'] += 1

        # 补充 RT_DATA 价格（更精确）
        price_maps: Dict[str, Dict[str, float]] = defaultdict(dict)
        try:
            rt_rows = self._db.execute_query(f"""
                SELECT stock_code, substr(time, 12, 5) as t, cur_price
                FROM rt_data
                WHERE stock_code IN ({placeholders}) AND trade_date = ?
                ORDER BY stock_code, time
            """, (*stock_codes, today_str))
            if rt_rows:
                for r in rt_rows:
                    if r[2] and float(r[2]) > 0:
                        price_maps[r[0]][r[1]] = float(r[2])
        except Exception:
            pass

        # 获取股票名称
        name_map = {}
        try:
            name_rows = self._db.execute_query(
                f"SELECT code, name FROM stocks WHERE code IN ({placeholders})",
                tuple(stock_codes)
            )
            if name_rows:
                name_map = {r[0]: r[1] for r in name_rows}
        except Exception:
            pass

        # 逐股票检测吸收
        now = datetime.now()
        for code, minutes_data in stock_minutes.items():
            if len(minutes_data) < self.MIN_WINDOW:
                continue

            # 冷却检查
            last_alert = self._cooldown.get(code)
            if last_alert and (now - last_alert).total_seconds() < self.COOLDOWN_MINUTES * 60:
                continue

            # 构建带价格的时间线
            timeline = []
            for minute in sorted(minutes_data.keys()):
                e = minutes_data[minute]
                net = e['buy'] - e['sell']
                # 价格优先 RT_DATA
                price = price_maps.get(code, {}).get(minute, 0)
                if price == 0 and e['price_n'] > 0:
                    price = e['price_sum'] / e['price_n']

                timeline.append({
                    'time': minute,
                    'net_buy': round(net / 10000, 1),  # 万
                    'price': round(price, 3) if price > 0 else 0,
                })

            # 检测吸收
            result = self._detect(timeline)
            if result:
                result['stock_code'] = code
                result['stock_name'] = name_map.get(code, '')
                alerts.append(result)
                self._cooldown[code] = now

        if alerts:
            logger.info(f"[吸收扫描] 检测到 {len(alerts)} 只股票存在买入吸收: "
                        f"{', '.join(a['stock_code'] for a in alerts)}")

        return alerts

    def _detect(self, timeline: List[Dict]) -> Optional[Dict]:
        """检测单只股票的吸收模式"""
        priced = [p for p in timeline if p.get('price', 0) > 0]
        if len(priced) < self.MIN_WINDOW:
            return None

        best = None
        i = 0
        while i < len(priced):
            if priced[i].get('net_buy', 0) <= 0:
                i += 1
                continue

            j = i
            while j < len(priced) and priced[j].get('net_buy', 0) > 0:
                j += 1

            window_len = j - i
            if window_len >= self.MIN_WINDOW:
                start_price = priced[i]['price']
                end_price = priced[j - 1]['price']
                pct = (end_price - start_price) / start_price * 100 if start_price > 0 else 0
                cum_buy = sum(p['net_buy'] for p in priced[i:j])

                if pct <= self.PRICE_THRESHOLD and cum_buy > 0:
                    severity = 'high' if window_len >= 8 or (window_len >= 5 and pct < -0.1) else 'medium'
                    candidate = {
                        'detected': True,
                        'severity': severity,
                        'start_time': priced[i]['time'],
                        'end_time': priced[j - 1]['time'],
                        'duration_min': window_len,
                        'price_change_pct': round(pct, 2),
                        'cum_net_buy': round(cum_buy, 1),
                        'start_price': round(start_price, 3),
                        'end_price': round(end_price, 3),
                        'message': (
                            f"{priced[i]['time']}~{priced[j-1]['time']}"
                            f" 连续{window_len}分钟主买 净买{cum_buy:.0f}万"
                            f" 但股价{'下跌' if pct < -0.05 else '持平'}"
                            f"({pct:+.2f}%)，疑似压单吸收"
                        ),
                    }
                    if best is None or window_len > best['duration_min']:
                        best = candidate

            i = j

        return best
