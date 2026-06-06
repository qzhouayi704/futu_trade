#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
全池快照扫描器 — 盘中资金建仓发现

每1分钟扫描全部目标股票池（~560只），通过 get_market_snapshot + capital_flow_cache
发现资金正在建仓的股票（资金评分≥75 + 净流入≥3% + 涨幅<3%），
再结合历史K线补充形态标签。

触发条件（两层过滤）：
  第一层（资金流）：资金评分≥75+净流入≥3%+涨幅<3%，或大单买≥60%+涨幅<3%，或涨幅≥15%
  第二层（K线标签）：缩量蓄势标注（仅作为信息标签，不阻止通过）
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
    anomaly_type: str       # "capital_inflow" / "big_buy_driven" / "limit_up"
    has_shrinkage: bool     # 是否有缩量蓄势形态
    detected_at: str        # 发现时间
    detail: str = ""        # 补充说明
    cap_tier: str = ""      # "large" / "mid" / "small" — 供策略层决定止盈方式
    capital_score: float = 0.0   # 资金评分 0-100
    signal_change: float = 0.0   # 信号时涨幅 %


class PoolSnapshotScanner:
    """全池快照扫描器"""

    # 第一层：资金流驱动阈值（所有入口必须经过资金验证）
    CAPITAL_SCORE_MIN = 75       # 资金评分最低分
    NET_INFLOW_RATIO_MIN = 0.03  # 净流入占比最低 3%
    BIG_BUY_RATIO_MIN = 0.60     # 大单买比最低 60%
    MAX_SIGNALS = 15             # 每次扫描最多推送信号数

    # 成交额分层阈值
    TURNOVER_LARGE = 1e8         # 大盘股成交额 ≥ 1亿
    TURNOVER_MID = 3e7           # 中盘股成交额 ≥ 3千万
    TURNOVER_MIN = 1e7           # 最低成交额 1千万

    # 第二层：缩量蓄势验证阈值（仅作标签）
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
        """第一层：资金流驱动筛选（所有入口必须经过资金验证）

        通过条件（满足任一）：
          A. 资金评分≥75 + 净流入≥3%
          B. 大单买≥60%
        涨幅不设硬限制，通过排序自然降权。
        """
        # 批量获取所有股票的资金流数据
        codes = [s['code'] for s in data]
        capital_map = self._batch_get_capital_flow(codes)

        candidates = []
        for stock in data:
            code = stock['code']
            chg = stock['change_rate']

            # 最低成交额过滤
            est_turnover = stock.get('volume', 0) * stock.get('last_price', 0)
            if est_turnover < self.TURNOVER_MIN:
                continue

            # 分层标签
            if est_turnover >= self.TURNOVER_LARGE:
                cap_tier = "large"
            elif est_turnover >= self.TURNOVER_MID:
                cap_tier = "mid"
            else:
                cap_tier = "small"

            # 资金流验证（唯一入口）
            cf = capital_map.get(code)
            if not cf:
                continue

            cap_score = cf.get('capital_score', 0)
            net_ratio = cf.get('net_inflow_ratio', 0)
            big_buy = cf.get('big_order_buy_ratio', 0)
            anomaly_type = None

            # 入口A: 资金评分+净流入
            if (cap_score >= self.CAPITAL_SCORE_MIN and
                    net_ratio >= self.NET_INFLOW_RATIO_MIN):
                anomaly_type = "capital_inflow"

            # 入口B: 大单买比
            elif big_buy >= self.BIG_BUY_RATIO_MIN:
                anomaly_type = "big_buy_driven"
                cap_score = cap_score or 50  # 保底评分

            if anomaly_type:
                stock['anomaly_type'] = anomaly_type
                stock['cap_tier'] = cap_tier
                stock['capital_score'] = cap_score
                stock['signal_change'] = chg
                candidates.append(stock)

        # 按资金强度排序，取TOP N
        if len(candidates) > self.MAX_SIGNALS:
            candidates = self._rank_by_capital_strength(candidates)

        return candidates

    def _rank_by_capital_strength(self, candidates: List[Dict]) -> List[Dict]:
        """按资金强度综合评分排序，取TOP MAX_SIGNALS

        涨幅不设硬限制，通过入场位置得分自然降权：
        涨幅越低得分越高，但资金特别强的股票即使涨5%也能排进来。
        当天有mega_sell信号的股票降分（回测: 有mega_sell的D2胜率0%）。
        """
        # 获取当天Sniper信号统计（从Sniper内存读取，无DB开销）
        sniper_stats = {}  # stock_code -> {'sell': count, 'buy': count}
        try:
            sniper = getattr(self.container, 'intraday_sniper', None)
            if sniper and hasattr(sniper, '_today_signals'):
                for s in sniper._today_signals:
                    if s.signal_type in ('mega_buy', 'mega_sell'):
                        stats = sniper_stats.setdefault(s.stock_code, {'sell': 0, 'buy': 0})
                        if s.signal_type == 'mega_sell':
                            stats['sell'] += 1
                        else:
                            stats['buy'] += 1
        except Exception:
            pass

        def score_fn(stock):
            cap_score = stock.get('capital_score', 0)
            chg = stock.get('signal_change', 0)

            # 入场位置得分：涨幅越低越好（软降权，不硬排除）
            if 0 <= chg < 1:
                position_score = 100
            elif 1 <= chg < 2:
                position_score = 80
            elif chg < 0:
                position_score = 60
            elif 2 <= chg < 3:
                position_score = 40
            elif 3 <= chg < 5:
                position_score = 20
            else:
                position_score = 10  # 涨≥5%仍可入选，但排名靠后

            # Sniper预警降分：按信号数量递增
            # 回测: 5+信号D1胜率13%, 买卖交替=主力对倒/出货
            code = stock.get('code', '')
            stats = sniper_stats.get(code)
            sniper_penalty = 0
            if stats:
                sell_n = stats['sell']
                total_n = stats['sell'] + stats['buy']
                if total_n >= 5:
                    sniper_penalty = 50   # 信号频繁交替 → 重罚
                elif sell_n >= 3:
                    sniper_penalty = 40   # 多次砸盘
                elif sell_n >= 1:
                    sniper_penalty = 20   # 有砸盘信号

            # 综合得分 = 资金评分(50%) + 入场位置(30%) + 净流入额外(20%) - Sniper降分
            return cap_score * 0.5 + position_score * 0.3 + cap_score * 0.2 - sniper_penalty

        candidates.sort(key=score_fn, reverse=True)
        return candidates[:self.MAX_SIGNALS]

    def _batch_get_capital_flow(self, codes: List[str]) -> Dict[str, dict]:
        """批量从 capital_flow_cache 获取最新资金流数据（3分钟内有效）"""
        if not codes:
            return {}

        try:
            db = self._container.db_manager
            placeholders = ','.join('?' * len(codes))

            rows = db.execute_query(f"""
                SELECT stock_code, capital_score, net_inflow_ratio,
                       big_order_buy_ratio, main_net_inflow
                FROM capital_flow_cache
                WHERE stock_code IN ({placeholders})
                  AND timestamp > datetime('now', '-3 minutes')
                ORDER BY timestamp DESC
            """, codes)

            result = {}
            if rows:
                for row in rows:
                    code = row[0]
                    if code not in result:  # 只取最新一条
                        result[code] = {
                            'capital_score': row[1] or 0,
                            'net_inflow_ratio': row[2] or 0,
                            'big_order_buy_ratio': row[3] or 0,
                            'main_net_inflow': row[4] or 0,
                        }
            return result

        except Exception as e:
            logger.warning(f"[异动扫描] 批量查询资金流失败: {e}")
            return {}


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
                cap_tier=stock.get('cap_tier', ''),
                capital_score=stock.get('capital_score', 0.0),
                signal_change=stock.get('signal_change', 0.0),
            ))

        return confirmed
