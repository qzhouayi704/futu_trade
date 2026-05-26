#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
IntradaySniper — 盘中狙击手引擎

每3分钟扫描活跃股票池，检测5类关键信号并通过
WebSocket + 企业微信推送实时告警。

信号类型：
  🔴 巨量砸盘     — 单分钟净卖出 > 日均 × 15倍
  🟢 巨量抢筹     — 单分钟净买入 > 日均 × 15倍
  🔴 资金转负     — 累计净流入由正转负（超过阈值）
  🟢 资金转正     — 累计净流入由负转正（超过阈值）
  🟢 资金加速     — 最近3分钟净买入 > 前3分钟 × 8倍
  🔴 持续流出     — 最近20分钟累计净卖出 > 动态阈值

参数（经2026-05-26全量回测校准）：
  冷却期: 15分钟（同股票同类信号）
  红绿互斥: 15分钟（同股票不出矛盾信号）
  阈值按日成交额自适应（大/中/小盘动态调整）
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("sniper")


# ============================================================
# 信号数据结构
# ============================================================

@dataclass
class SniperSignal:
    """一条狙击手信号"""
    time: str               # HH:MM
    stock_code: str
    stock_name: str
    signal_type: str        # mega_sell / mega_buy / reversal_bear / reversal_bull / accel_in / sustained_out
    is_red: bool            # True=风险信号, False=机会信号
    price: float
    detail: str             # 人类可读描述
    action: str             # 建议动作
    severity: str = "high"  # high / medium

    @property
    def emoji(self) -> str:
        return "🔴" if self.is_red else "🟢"

    def to_dict(self) -> dict:
        return {
            "time": self.time,
            "stock_code": self.stock_code,
            "stock_name": self.stock_name,
            "signal_type": self.signal_type,
            "is_red": self.is_red,
            "emoji": self.emoji,
            "price": self.price,
            "detail": self.detail,
            "action": self.action,
            "severity": self.severity,
        }

    def to_wechat_text(self) -> str:
        return (
            f"**{self.emoji} {self.stock_name}({self.stock_code})**\n"
            f"- 价格：**{self.price:.3f}**\n"
            f"- 信号：{self.detail}\n"
            f"- 建议：{self.action}"
        )


# ============================================================
# 回测校准参数
# ============================================================

# 通用参数
SCAN_INTERVAL_MINUTES = 3      # 扫描间隔
ACCEL_THRESHOLD = 8.0          # 加速倍数阈值
MEGA_MULTIPLIER = 15           # 巨量砸盘/抢筹倍数阈值
SUSTAINED_RATIO = 0.35         # 持续流出强度比例
SUSTAINED_MINUTES = 20         # 持续流出检查窗口
COOLDOWN_MINUTES = 15          # 同类信号冷却期
CONFLICT_WINDOW_MINUTES = 15   # 红绿互斥窗口

# 按日成交额分档的动态阈值 (万元)
TIER_THRESHOLDS = {
    # (日成交额下限万, accel_min万, mega_min万, reversal_min万)
    'large':  (50000, 3000, 5000, 5000),   # 大盘 >5亿
    'mid':    (10000, 1500, 2000, 2000),    # 中盘 1-5亿
    'small':  (1000,  500,  800,  500),     # 小盘 1000万-1亿
}
MIN_DAILY_TURNOVER = 1000  # 日成交额 <1000万 的微盘股不监控


# ============================================================
# 核心引擎
# ============================================================

class IntradaySniper:
    """盘中狙击手引擎"""

    def __init__(self, container):
        self.container = container
        self._running = False

        # 每只股票的状态
        self._stock_states: Dict[str, dict] = {}
        # 今日已推送信号（供前端查询）
        self._today_signals: List[SniperSignal] = []
        # 上次扫描时间
        self._last_scan: Optional[datetime] = None

    # ==================== 公共接口 ====================

    async def start(self):
        """启动引擎（由 app.py 在启动时调用）"""
        self._running = True
        logger.info("IntradaySniper 引擎已启动")
        asyncio.create_task(self._scan_loop())

    async def stop(self):
        """停止引擎"""
        self._running = False
        logger.info("IntradaySniper 引擎已停止")

    def get_today_signals(self) -> List[dict]:
        """获取今日所有信号（供 API 查询）"""
        return [s.to_dict() for s in self._today_signals]

    def get_recent_signals(self, minutes: int = 30) -> List[dict]:
        """获取最近N分钟的信号"""
        now = datetime.now().strftime("%H:%M")
        cutoff_h = int(now[:2])
        cutoff_m = int(now[3:]) - minutes
        while cutoff_m < 0:
            cutoff_h -= 1
            cutoff_m += 60
        cutoff = f"{cutoff_h:02d}:{cutoff_m:02d}"
        return [s.to_dict() for s in self._today_signals if s.time >= cutoff]

    # ==================== 扫描循环 ====================

    async def _scan_loop(self):
        """主扫描循环"""
        while self._running:
            try:
                now = datetime.now()
                hhmm = now.strftime("%H:%M")

                # 只在交易时间扫描 (09:25-16:05)
                if "09:25" <= hhmm <= "16:05":
                    await self._do_scan()
                elif hhmm > "16:10":
                    # 收盘后清理状态，准备下一天
                    if self._stock_states:
                        logger.info(f"收盘，今日共产生 {len(self._today_signals)} 条信号")
                        self._stock_states.clear()

                # 等待到下一个扫描周期
                await asyncio.sleep(SCAN_INTERVAL_MINUTES * 60)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"扫描异常: {e}", exc_info=True)
                await asyncio.sleep(60)

    async def _do_scan(self):
        """执行一次扫描"""
        db = getattr(self.container, 'db_manager', None)
        if not db:
            return

        today = date.today().isoformat()
        self._last_scan = datetime.now()

        try:
            # 获取所有有今日逐笔数据的股票
            conn = db.get_connection()
            stocks = conn.execute(
                "SELECT DISTINCT stock_code FROM ticker_data WHERE trade_date = ?",
                (today,)
            ).fetchall()

            new_signals = []

            for (stock_code,) in stocks:
                # 加载分钟级数据
                timeline, avg_turnover, day_total = self._load_minute_data(
                    conn, stock_code, today
                )

                if len(timeline) < 10 or avg_turnover <= 0:
                    continue

                # 跳过微盘股
                if day_total < MIN_DAILY_TURNOVER:
                    continue

                # 获取股票名称
                stock_name = self._get_stock_name(conn, stock_code)

                # 确定阈值档位
                accel_min, mega_min, reversal_min = self._get_tier_thresholds(day_total)

                # 运行信号检测
                signals = self._detect_signals(
                    stock_code, stock_name, timeline,
                    avg_turnover, day_total,
                    accel_min, mega_min, reversal_min,
                )
                new_signals.extend(signals)

            # 推送新信号
            for sig in new_signals:
                self._today_signals.append(sig)
                await self._push_signal(sig)

            if new_signals:
                logger.info(f"本次扫描产生 {len(new_signals)} 条新信号")

        except Exception as e:
            logger.error(f"扫描执行异常: {e}", exc_info=True)

    # ==================== 信号检测 ====================

    def _detect_signals(
        self,
        stock_code: str,
        stock_name: str,
        timeline: List[dict],
        avg_turnover: float,
        day_total: float,
        accel_min: float,
        mega_min: float,
        reversal_min: float,
    ) -> List[SniperSignal]:
        """对单只股票检测信号"""

        # 获取或初始化该股票的状态
        if stock_code not in self._stock_states:
            self._stock_states[stock_code] = {
                'prev_cum_direction': 'neutral',
                'cooldown': {},      # signal_type -> last_trigger_index
                'recent_signals': [],  # [(time, is_red, index)]
                'last_processed_index': -1,
            }

        state = self._stock_states[stock_code]
        signals = []

        # 只处理上次扫描以后的新数据点
        start_idx = max(state['last_processed_index'] + 1, 0)

        # 动态巨量阈值
        dynamic_mega = max(mega_min, avg_turnover * MEGA_MULTIPLIER)
        # 动态持续流出阈值
        dynamic_sustained = max(
            SUSTAINED_RATIO * avg_turnover * SUSTAINED_MINUTES,
            mega_min * 0.6,
        )

        for i in range(start_idx, len(timeline)):
            point = timeline[i]
            minute = point['time']
            is_scan_point = (i % SCAN_INTERVAL_MINUTES == 0 and i > 0)

            # --- 辅助函数 ---
            def can_emit(sig_type: str, is_red: bool) -> bool:
                # 冷却检查
                if sig_type in state['cooldown']:
                    if i - state['cooldown'][sig_type] < COOLDOWN_MINUTES:
                        return False
                # 冲突检查
                cutoff = max(0, i - CONFLICT_WINDOW_MINUTES)
                for _, r_is_red, r_idx in state['recent_signals']:
                    if r_idx >= cutoff:
                        if (is_red and not r_is_red) or (not is_red and r_is_red):
                            return False
                return True

            def emit(sig_type: str, is_red: bool, detail: str, action: str):
                state['cooldown'][sig_type] = i
                state['recent_signals'].append((minute, is_red, i))
                # 清理过期记录
                cutoff = max(0, i - CONFLICT_WINDOW_MINUTES * 2)
                state['recent_signals'] = [
                    r for r in state['recent_signals'] if r[2] >= cutoff
                ]
                signals.append(SniperSignal(
                    time=minute, stock_code=stock_code, stock_name=stock_name,
                    signal_type=sig_type, is_red=is_red,
                    price=point['price'], detail=detail, action=action,
                ))

            # === 信号1: 巨量砸盘 ===
            if point['net'] < -dynamic_mega:
                if can_emit('mega_sell', True):
                    mult = abs(point['net'] / avg_turnover) if avg_turnover > 0 else 0
                    emit('mega_sell', True,
                         f"单分钟净卖出{point['net']:.0f}万(日均{mult:.0f}倍)",
                         "❌ 不要买入/立即止损")

            # === 信号2: 巨量抢筹 ===
            if point['net'] > dynamic_mega:
                if can_emit('mega_buy', False):
                    mult = point['net'] / avg_turnover if avg_turnover > 0 else 0
                    emit('mega_buy', False,
                         f"单分钟净买入+{point['net']:.0f}万(日均{mult:.0f}倍)",
                         "✅ 关注买入机会")

            # === 每3分钟扫描的信号 ===
            if is_scan_point:
                curr_dir = (
                    'positive' if point['cum_net'] > 0
                    else 'negative' if point['cum_net'] < 0
                    else 'neutral'
                )

                # 信号3: 资金反转 (由负转正)
                if (state['prev_cum_direction'] == 'negative'
                        and curr_dir == 'positive'
                        and point['cum_net'] > reversal_min):
                    if can_emit('reversal_bull', False):
                        emit('reversal_bull', False,
                             f"累计净流入由负转正: {point['cum_net']:.0f}万",
                             "✅ 资金反转，关注入场")

                # 信号4: 资金反转 (由正转负)
                if (state['prev_cum_direction'] == 'positive'
                        and curr_dir == 'negative'
                        and point['cum_net'] < -reversal_min):
                    if can_emit('reversal_bear', True):
                        emit('reversal_bear', True,
                             f"累计净流入由正转负: {point['cum_net']:.0f}万",
                             "❌ 资金反转，考虑减仓")

                # 信号5: 资金加速流入
                if i >= 6:
                    recent_3 = sum(timeline[j]['net'] for j in range(i - 2, i + 1))
                    prev_3 = sum(timeline[j]['net'] for j in range(i - 5, i - 2))
                    if (prev_3 > 0
                            and recent_3 > prev_3 * ACCEL_THRESHOLD
                            and recent_3 > accel_min):
                        if can_emit('accel_in', False):
                            emit('accel_in', False,
                                 f"3分钟净买+{recent_3:.0f}万"
                                 f"(前3分钟+{prev_3:.0f}万，{recent_3/prev_3:.0f}倍加速)",
                                 "✅ 资金加速流入")

                # 信号6: 持续流出
                if i >= SUSTAINED_MINUTES:
                    window_net = sum(
                        timeline[j]['net']
                        for j in range(i - SUSTAINED_MINUTES + 1, i + 1)
                    )
                    if window_net < -dynamic_sustained:
                        if can_emit('sustained_out', True):
                            emit('sustained_out', True,
                                 f"最近{SUSTAINED_MINUTES}分钟累计净卖出{window_net:.0f}万",
                                 "❌ 持续流出，不宜入场")

                state['prev_cum_direction'] = curr_dir

        # 更新已处理的索引
        state['last_processed_index'] = len(timeline) - 1
        return signals

    # ==================== 数据加载 ====================

    @staticmethod
    def _load_minute_data(conn, stock_code: str, today: str):
        """从 ticker_data 加载分钟级聚合数据"""
        rows = conn.execute("""
            SELECT
                substr(datetime(timestamp/1000, 'unixepoch', '+8 hours'), 12, 5) as minute,
                direction, SUM(turnover) as tv, AVG(price) as ap
            FROM ticker_data
            WHERE stock_code = ? AND trade_date = ?
            GROUP BY minute, direction
            ORDER BY minute
        """, (stock_code, today)).fetchall()

        minutes = {}
        for minute, direction, turnover, avg_price in rows:
            if not ('09:15' <= minute <= '16:10'):
                continue
            if minute not in minutes:
                minutes[minute] = {'buy': 0.0, 'sell': 0.0, 'price': 0, 'price_n': 0}
            entry = minutes[minute]
            tv = float(turnover or 0)
            if direction == 'BUY':
                entry['buy'] += tv
            elif direction == 'SELL':
                entry['sell'] += tv
            if avg_price and float(avg_price) > 0:
                entry['price'] += float(avg_price)
                entry['price_n'] += 1

        timeline = []
        cum_buy, cum_sell = 0.0, 0.0
        for minute in sorted(minutes.keys()):
            e = minutes[minute]
            cum_buy += e['buy']
            cum_sell += e['sell']
            net = e['buy'] - e['sell']
            price = round(e['price'] / e['price_n'], 3) if e['price_n'] > 0 else 0
            timeline.append({
                'time': minute,
                'net': round(net / 10000, 1),
                'cum_net': round((cum_buy - cum_sell) / 10000, 1),
                'price': price,
                'turnover': round((e['buy'] + e['sell']) / 10000, 1),
            })

        turnovers = [p['turnover'] for p in timeline if p['turnover'] > 0]
        avg_turnover = sum(turnovers) / len(turnovers) if turnovers else 0
        day_total = sum(p['turnover'] for p in timeline)
        return timeline, avg_turnover, day_total

    @staticmethod
    def _get_stock_name(conn, stock_code: str) -> str:
        """获取股票名称"""
        try:
            row = conn.execute(
                "SELECT name FROM stocks WHERE code = ?", (stock_code,)
            ).fetchone()
            return row[0] if row else stock_code
        except Exception:
            return stock_code

    @staticmethod
    def _get_tier_thresholds(day_total: float) -> Tuple[float, float, float]:
        """根据日成交额确定阈值档位"""
        for tier_name, (min_turnover, accel_min, mega_min, reversal_min) in TIER_THRESHOLDS.items():
            if day_total >= min_turnover:
                return accel_min, mega_min, reversal_min
        # 小盘兜底
        return 500, 800, 500

    # ==================== 推送 ====================

    async def _push_signal(self, signal: SniperSignal):
        """推送信号到 WebSocket + 企业微信"""
        # 1. WebSocket 推送
        try:
            socket_manager = getattr(self.container, '_socket_manager', None)
            if not socket_manager:
                from ...dependencies import get_socket_manager
                socket_manager = get_socket_manager()
            if socket_manager:
                await socket_manager.emit_to_all('sniper_signal', signal.to_dict())
            logger.info(f"📡 {signal.emoji} {signal.stock_name} {signal.detail}")
        except Exception as e:
            logger.debug(f"WebSocket推送失败: {e}")

        # 2. 企业微信推送
        try:
            wechat = getattr(self.container, 'wechat_alert_service', None)
            if wechat and wechat.enabled:
                from ..alert.wechat_alert import AlertLevel
                level = AlertLevel.CRITICAL if signal.is_red else AlertLevel.INFO
                await wechat.send(
                    level=level,
                    title=f"盘中狙击 — {signal.stock_name}",
                    content=signal.to_wechat_text(),
                    dedup_key=f"sniper:{signal.stock_code}:{signal.signal_type}",
                )
        except Exception as e:
            logger.debug(f"企业微信推送失败: {e}")
