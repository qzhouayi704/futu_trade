#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
全池快照扫描器 — 盘中异动发现

每3分钟扫描全部目标股票池（~560只），通过 get_market_snapshot
发现涨幅+量比异常的股票，再结合历史K线验证是否有缩量蓄势形态，
过滤掉无延续性的纯游资炒作。

触发条件（两层过滤）：
  第一层（快照）：涨幅 ≥ 7% + 量比 ≥ 3，或涨幅 ≥ 15%
  第二层（K线验证）：前3日缩量 + 前5日振幅收窄 + 突破近期高点
"""

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Set

logger = logging.getLogger(__name__)


@dataclass
class AnomalyStock:
    """异动股票数据"""
    code: str
    name: str
    change_rate: float      # 今日涨跌幅 %
    volume_ratio: float     # 量比
    turnover_rate: float    # 当前换手率 %
    price: float            # 当前价格
    anomaly_type: str       # "breakout_surge" / "extreme_volume" / "limit_up"
    has_shrinkage: bool     # 是否有缩量蓄势形态
    detected_at: str        # 发现时间
    detail: str = ""        # 补充说明


class PoolSnapshotScanner:
    """全池快照扫描器"""

    # 第一层：快照异动阈值
    SURGE_CHANGE_PCT = 7.0       # 放量异动最低涨幅 %
    SURGE_VOLUME_RATIO = 3.0     # 放量异动最低量比
    STRONG_SURGE_CHANGE_PCT = 10.0  # 强势异动涨幅(不要求量比)
    EXTREME_VOLUME_RATIO = 5.0   # 极端放量量比（不论涨幅）
    LIMIT_UP_CHANGE_PCT = 15.0   # 涨停级涨幅 %

    # 第二层：缩量蓄势验证阈值
    SHRINKAGE_TR_MAX = 2.0       # 前3日换手率上限 %
    SHRINKAGE_RANGE_MAX = 15.0   # 前5日振幅上限 %
    SHRINKAGE_DAYS = 3           # 检查缩量的天数

    # 扫描控制
    BATCH_SIZE = 280             # 每批快照请求的股票数
    BATCH_DELAY = 1.0            # 批次间延迟（秒）

    def __init__(self, container):
        self._container = container
        self._last_anomalies: Dict[str, AnomalyStock] = {}  # code -> AnomalyStock
        self._cooldown: Dict[str, float] = {}  # code -> 上次触发时间
        self._cooldown_seconds = 1800  # 同一股票30分钟内不重复触发

    def scan(self) -> List[AnomalyStock]:
        """执行全池扫描，返回异动股列表

        流程：
        1. 从DB获取全部目标股票代码
        2. 分批调用 get_market_snapshot
        3. 第一层筛选：涨幅+量比
        4. 第二层验证：K线缩量蓄势形态
        """
        start = time.time()

        # 获取目标股票
        codes = self._get_pool_codes()
        if not codes:
            return []

        # 分批获取快照
        snapshot_data = self._fetch_snapshots(codes)
        if not snapshot_data:
            return []

        # 第一层：快照异动筛选
        candidates = self._filter_by_snapshot(snapshot_data)
        if not candidates:
            return []

        # 冷却期过滤
        candidates = self._apply_cooldown(candidates)
        if not candidates:
            return []

        # 第二层：K线形态验证
        confirmed = self._validate_with_kline(candidates)

        elapsed = round(time.time() - start, 1)
        if confirmed:
            from ...utils.logger import print_status
            codes_str = ', '.join([f"{a.code}({a.change_rate:+.1f}%)" for a in confirmed[:3]])
            print_status(
                f"【异动扫描】发现 {len(confirmed)} 只: {codes_str}",
                "warning"
            )
        else:
            logger.debug(
                f"[异动扫描] 全池 {len(codes)} 只, "
                f"快照候选 {len(candidates) if candidates else 0}, "
                f"确认 0, 耗时 {elapsed}s"
            )

        # 更新缓存
        for a in confirmed:
            self._last_anomalies[a.code] = a
            self._cooldown[a.code] = time.time()

        return confirmed

    def get_last_anomalies(self) -> List[AnomalyStock]:
        """获取最近一次扫描的异动结果"""
        return list(self._last_anomalies.values())

    def get_rotation_candidates(self) -> List[str]:
        """返回应替换进订阅列表的异动股代码"""
        sub_mgr = getattr(self._container, 'subscription_manager', None)
        if not sub_mgr:
            return []
        subscribed = sub_mgr.subscribed_stocks
        return [
            a.code for a in self._last_anomalies.values()
            if a.code not in subscribed and a.has_shrinkage
        ]

    # ==================== 内部方法 ====================

    def _get_pool_codes(self) -> List[str]:
        """从DB获取全部目标板块股票代码"""
        try:
            rows = self._container.db_manager.execute_query("""
                SELECT DISTINCT s.code
                FROM stocks s
                INNER JOIN stock_plates sp ON s.id = sp.stock_id
                INNER JOIN plates p ON sp.plate_id = p.id
                WHERE p.is_target = 1 AND p.is_enabled = 1
                  AND (s.is_otc IS NULL OR s.is_otc = 0)
                  AND s.market = 'HK'
            """)
            codes = [r[0] for r in rows] if rows else []
            return codes
        except Exception as e:
            logger.error(f"[异动扫描] 获取股票池失败: {e}")
            return []

    def _fetch_snapshots(self, codes: List[str]) -> List[Dict[str, Any]]:
        """分批获取市场快照"""
        futu_client = self._container.futu_client
        if not futu_client.is_available():
            return []

        all_data = []
        for i in range(0, len(codes), self.BATCH_SIZE):
            batch = codes[i:i + self.BATCH_SIZE]
            try:
                ret, data = futu_client.get_market_snapshot(batch)
                if ret == 0 and data is not None and not data.empty:
                    for _, row in data.iterrows():
                        all_data.append({
                            'code': row.get('code', ''),
                            'name': row.get('name', ''),
                            'last_price': float(row.get('last_price', 0)),
                            'change_rate': float(row.get('change_rate', 0)),
                            'volume_ratio': float(row.get('volume_ratio', 0) or 0),
                            'turnover_rate': float(row.get('turnover_rate', 0) or 0),
                            'volume': int(row.get('volume', 0)),
                        })
                if i + self.BATCH_SIZE < len(codes):
                    time.sleep(self.BATCH_DELAY)
            except Exception as e:
                logger.warning(f"[异动扫描] 批次快照失败: {e}")

        return all_data

    def _filter_by_snapshot(self, data: List[Dict]) -> List[Dict]:
        """第一层：快照异动筛选"""
        candidates = []
        for stock in data:
            chg = stock['change_rate']
            vr = stock['volume_ratio']

            anomaly_type = None
            if chg >= self.LIMIT_UP_CHANGE_PCT:
                anomaly_type = "limit_up"
            elif chg >= self.STRONG_SURGE_CHANGE_PCT:
                anomaly_type = "strong_surge"  # 涨幅≥10%无需量比
            elif chg >= self.SURGE_CHANGE_PCT and vr >= self.SURGE_VOLUME_RATIO:
                anomaly_type = "breakout_surge"
            elif vr >= self.EXTREME_VOLUME_RATIO and chg > 0:
                anomaly_type = "extreme_volume"

            if anomaly_type:
                stock['anomaly_type'] = anomaly_type
                candidates.append(stock)

        return candidates

    def _apply_cooldown(self, candidates: List[Dict]) -> List[Dict]:
        """冷却期过滤：同一股票30分钟内不重复触发"""
        now = time.time()
        filtered = []
        for c in candidates:
            code = c['code']
            last_time = self._cooldown.get(code, 0)
            if now - last_time >= self._cooldown_seconds:
                filtered.append(c)
        return filtered

    def _validate_with_kline(self, candidates: List[Dict]) -> List[AnomalyStock]:
        """第二层：用历史K线补充形态标签（不再作为过滤条件）"""
        confirmed = []
        db = self._container.db_manager

        for stock in candidates:
            code = stock['code']
            has_shrinkage = False
            detail = ""

            try:
                # 查询最近10天K线（排除今天）
                rows = db.execute_query("""
                    SELECT time_key, open_price, high_price, low_price,
                           close_price, volume, turnover_rate
                    FROM kline_data
                    WHERE stock_code = ?
                    ORDER BY time_key DESC
                    LIMIT 10
                """, (code,))

                if rows and len(rows) >= 3:
                    # 前3日换手率
                    recent_trs = [r[6] for r in rows[:3] if r[6] is not None]
                    avg_tr = sum(recent_trs) / len(recent_trs) if recent_trs else 999

                    # 前5日振幅
                    if len(rows) >= 5:
                        highs = [r[2] for r in rows[:5]]
                        lows = [r[3] for r in rows[:5]]
                        max_h = max(highs)
                        min_l = min(lows)
                        price_range = (max_h - min_l) / min_l * 100 if min_l > 0 else 999
                    else:
                        price_range = 999

                    # 检查是否突破近期高点
                    recent_highs = [r[2] for r in rows[:5]] if len(rows) >= 5 else []
                    max_recent_high = max(recent_highs) if recent_highs else 0
                    breaking_high = stock['last_price'] > max_recent_high if max_recent_high > 0 else False

                    # 缩量蓄势标注（仅作为信息，不再阻止通过）
                    if (avg_tr <= self.SHRINKAGE_TR_MAX and
                            price_range <= self.SHRINKAGE_RANGE_MAX):
                        has_shrinkage = True
                        detail = (
                            f"缩量蓄势: 前3日均TR={avg_tr:.2f}%, "
                            f"5日振幅={price_range:.1f}%, "
                            f"破新高={'✓' if breaking_high else '✗'}"
                        )
                    else:
                        detail = f"放量趋势: 前3日均TR={avg_tr:.2f}%, 5日振幅={price_range:.1f}%"

                elif not rows:
                    detail = "无K线历史"

            except Exception as e:
                logger.debug(f"[异动扫描] {code} K线验证失败: {e}")
                detail = f"验证异常: {e}"

            # 所有通过第一层筛选的异动股都保留，缩量仅作为标签
            confirmed.append(AnomalyStock(
                code=code,
                name=stock.get('name', ''),
                change_rate=stock['change_rate'],
                volume_ratio=stock['volume_ratio'],
                turnover_rate=stock['turnover_rate'],
                price=stock['last_price'],
                anomaly_type=stock['anomaly_type'],
                has_shrinkage=has_shrinkage,
                detected_at=datetime.now().strftime('%H:%M:%S'),
                detail=detail,
            ))

        return confirmed
