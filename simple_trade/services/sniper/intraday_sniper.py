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
    strength: int = 0       # 信号强度评分 (0-100)，仅 mega_buy 使用
    strength_label: str = ""  # 强度标签，如 "★★★ 强"

    @property
    def emoji(self) -> str:
        return "🔴" if self.is_red else "🟢"

    def to_dict(self) -> dict:
        d = {
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
        if self.strength > 0:
            d["strength"] = self.strength
            d["strength_label"] = self.strength_label
        return d

    def to_wechat_text(self) -> str:
        strength_line = f"\n- 强度：**{self.strength_label}** ({self.strength}/100)" if self.strength > 0 else ""
        return (
            f"**{self.emoji} {self.stock_name}({self.stock_code})**\n"
            f"- 价格：**{self.price:.3f}**{strength_line}\n"
            f"- 信号：{self.detail}\n"
            f"- 建议：{self.action}"
        )


# ============================================================
# 回测校准参数
# ============================================================

# 通用参数
SCAN_INTERVAL_MINUTES = 3      # 扫描间隔
ACCEL_THRESHOLD = 3.0          # 回退: 1.5→3 (tick回放验证旧参数更优, 73%胜率+2.62% vs 64%胜率-0.74%)
MEGA_MULTIPLIER = 3            # 回退: 5→3 (MEGA=3检测到更多有效mega_buy信号)
SUSTAINED_RATIO = 0.35         # 持续流出强度比例
SUSTAINED_MINUTES = 20         # 持续流出检查窗口
COOLDOWN_MINUTES = 15          # 同类信号冷却期
CONFLICT_WINDOW_MINUTES = 15   # 红绿互斥窗口

# 双窗口评分参数（经回测最优: 短3分钟+长30分钟）
SCORE_SHORT_WINDOW = 3         # 短窗口(分钟): 捕捉突发异动
SCORE_LONG_WINDOW = 30         # 长窗口(分钟): 捕捉趋势建仓
SCORE_SHORT_FLOW_THRESH = 60   # 短窗口资金阈值(万)
SCORE_LONG_FLOW_THRESH = 300   # 长窗口资金阈值(万)
SCORE_SHORT_CHG_THRESH = 0.2   # 短窗口价格变化阈值(%)
SCORE_LONG_CHG_THRESH = 0.3    # 长窗口价格变化阈值(%)
SCORE_SIGNAL_WEIGHT = 3        # 信号分权重

# 动态阈值参数 (方案C: 混合动态 — 替代固定分档)
MEGA_FLOOR_PCT = 0.02      # 动态mega阈值地板 = 日成交额 × 2%
MEGA_FLOOR_MIN = 50        # 最低地板50万(防微盘股误触发)
MIN_DAILY_TURNOVER = 100   # 日成交额 <100万 不监控(放宽)


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
        # TOP 排行榜（每次扫描更新）
        self._top_ranking: dict = {'opportunity': [], 'risk': [], 'updated_at': None}

    # ==================== 公共接口 ====================

    async def start(self):
        """启动引擎（由 app.py 在启动时调用）"""
        self._running = True
        # 从 DB 恢复今日信号（重启不丢数据）
        self._load_today_signals_from_db()
        logger.info(f"IntradaySniper 引擎已启动, 从DB恢复 {len(self._today_signals)} 条今日信号")
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

    def get_top_ranking(self) -> dict:
        """获取当前 TOP 排行榜"""
        return self._top_ranking

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
                        # 输出盘后筛选日志到数据盘
                        try:
                            engine = getattr(self.container, 'trade_decision_engine', None)
                            if engine:
                                engine.log_daily_screening_summary()
                        except Exception as e:
                            logger.warning(f"盘后日志输出失败: {e}")
                        self._stock_states.clear()

                # 等待到下一个扫描周期
                await asyncio.sleep(SCAN_INTERVAL_MINUTES * 60)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"扫描异常: {e}", exc_info=True)
                await asyncio.sleep(60)

    async def _do_scan(self):
        """执行一次扫描（只扫描用户股票池中的股票）"""
        db = getattr(self.container, 'db_manager', None)
        if not db:
            return

        today = date.today().isoformat()
        self._last_scan = datetime.now()

        try:
            # 获取用户股票池（已订阅的股票）
            sub_mgr = getattr(self.container, 'subscription_manager', None)
            if sub_mgr and hasattr(sub_mgr, 'subscribed_stocks'):
                watch_codes = list(sub_mgr.subscribed_stocks)
            else:
                # fallback: 从 ticker_data 获取全部（不推荐）
                conn = db.get_connection()
                rows = conn.execute(
                    "SELECT DISTINCT stock_code FROM ticker_data WHERE trade_date = ?",
                    (today,)
                ).fetchall()
                watch_codes = [r[0] for r in rows]

            if not watch_codes:
                return

            with db.get_connection() as conn:
                new_signals = []

                for stock_code in watch_codes:
                    # 加载分钟级数据
                    timeline, avg_turnover, day_total = self._load_minute_data(
                        conn, stock_code, today
                    )

                    if len(timeline) < 2 or avg_turnover <= 0:
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

                    # 席位交叉验证：对 mega_buy 信号进行画像核验
                    # 计算当日实际涨幅（用于 BrokerConsistencyFilter 的涨幅加成判断）
                    change_pct = 0.0
                    if len(timeline) >= 2 and timeline[0]['price'] > 0:
                        change_pct = round(
                            (timeline[-1]['price'] - timeline[0]['price']) / timeline[0]['price'] * 100, 2
                        )

                    broker_checked = False  # 标记：避免下方独立检测重复调用
                    for sig in signals:
                        if sig.signal_type == 'mega_buy':
                            broker_acc_conf = 0.0
                            broker_trap_conf = 0.0
                            try:
                                from ..analysis.flow.broker_consistency_filter import BrokerConsistencyFilter
                                bf = BrokerConsistencyFilter(self.container.futu_client)
                                trap_res = bf.check_distribution_trap(stock_code, change_pct=change_pct)
                                acc_res = bf.check_accumulation_signal(stock_code, change_pct=change_pct)
                                broker_checked = True

                                if trap_res.is_trap:
                                    sig.detail += f" (⚠️席位警示: 存在出货迹象, 置信度{trap_res.trap_confidence:.0%})"
                                    sig.severity = "medium"
                                    broker_trap_conf = trap_res.trap_confidence
                                elif acc_res.is_trap:
                                    sig.detail += f" (🔥席位确认: 机构吸筹中, 置信度{acc_res.trap_confidence:.0%})"
                                    sig.severity = "high"
                                    broker_acc_conf = acc_res.trap_confidence
                                else:
                                    sig.detail += " (⚠️席位确认: 散户/未知席位主导，警惕拉高出货)"
                                    sig.severity = "medium"
                            except Exception as e:
                                logger.debug(f"验证mega_buy席位失败: {e}")

                            # 计算强度评分
                            try:
                                # 从 detail 提取倍数 (格式: "日均X倍")
                                import re
                                mult_match = re.search(r'日均(\d+)倍', sig.detail)
                                sig_mult = float(mult_match.group(1)) if mult_match else 0.0

                                strength, label, ctx = self._calc_mega_buy_strength(
                                    stock_code, sig_mult, timeline,
                                    broker_acc_confidence=broker_acc_conf,
                                    broker_trap_confidence=broker_trap_conf,
                                    change_pct=change_pct,
                                )
                                sig.strength = strength
                                sig.strength_label = label
                                if ctx:
                                    sig.detail += f" [{label} {strength}分: {ctx}]"
                                else:
                                    sig.detail += f" [{label} {strength}分]"
                                logger.info(
                                    f"📡 {sig.emoji} {sig.stock_name} "
                                    f"巨量抢筹 {label}({strength}/100)"
                                    + (f" | {ctx}" if ctx else "")
                                )
                            except Exception as e:
                                logger.debug(f"强度评分计算失败: {stock_code}: {e}")

                    new_signals.extend(signals)

                    # 经纪商偏向检测（单次盘口快照，互斥裁决出货陷阱 vs 主力吸筹）
                    # 使用统一冷却：任意一方触发均重置，防止同一股票在同一窗口重复检测
                    last_broker_idx = max(
                        self._stock_states.get(stock_code, {}).get('last_trap_idx', -999),
                        self._stock_states.get(stock_code, {}).get('last_acc_idx', -999),
                    )
                    if not broker_checked and len(timeline) - last_broker_idx >= COOLDOWN_MINUTES // SCAN_INTERVAL_MINUTES:
                        try:
                            from ..analysis.flow.broker_consistency_filter import (
                                BrokerConsistencyFilter, BiasSignal,
                            )
                            bf = BrokerConsistencyFilter(self.container.futu_client)
                            bias = bf.analyze_broker_bias(stock_code, change_pct=change_pct)
                            price = timeline[-1]['price'] if timeline else 0

                            if bias.signal == BiasSignal.DISTRIBUTION_TRAP:
                                trap_sig = SniperSignal(
                                    time=datetime.now().strftime("%H:%M"),
                                    stock_code=stock_code,
                                    stock_name=stock_name,
                                    signal_type="distribution_trap",
                                    is_red=True,
                                    price=price,
                                    detail=bias.reason,
                                    action="⚠️ 警惕主力出货，不宜追买",
                                    severity="high",
                                )
                                new_signals.append(trap_sig)
                                if stock_code in self._stock_states:
                                    self._stock_states[stock_code]['last_trap_idx'] = len(timeline)
                                    self._stock_states[stock_code]['last_acc_idx'] = len(timeline)

                            elif bias.signal == BiasSignal.ACCUMULATION:
                                acc_sig = SniperSignal(
                                    time=datetime.now().strftime("%H:%M"),
                                    stock_code=stock_code,
                                    stock_name=stock_name,
                                    signal_type="accumulation_signal",
                                    is_red=False,
                                    price=price,
                                    detail=bias.reason,
                                    action="🟢 机构吸筹中，关注买入机会",
                                    severity="high",
                                )
                                new_signals.append(acc_sig)
                                if stock_code in self._stock_states:
                                    self._stock_states[stock_code]['last_trap_idx'] = len(timeline)
                                    self._stock_states[stock_code]['last_acc_idx'] = len(timeline)

                        except Exception as e:
                            logger.debug(f"经纪商偏向检测异常: {stock_code}: {e}")

                # 先更新 TOP 排行榜（用于过滤信号）
                self._update_ranking(conn, watch_codes, today)

                # 推送逻辑：在TOP 5排行榜内，或者属于强机构确认信号（主力吸筹、机构确认的巨量抢筹）均进行实时推送
                top_codes = {s['stock_code'] for s in self._top_ranking.get('opportunity', [])}
                pushed = 0
                for sig in new_signals:
                    self._today_signals.append(sig)
                    self._save_signal_to_db(sig)
                    
                    # 识别机构资金信号
                    is_inst_signal = (
                        sig.signal_type == 'accumulation_signal' or 
                        (sig.signal_type == 'mega_buy' and sig.severity == 'high')
                    )
                    
                    if sig.stock_code in top_codes or is_inst_signal:
                        await self._push_signal(sig)
                        pushed += 1

                    # 转发持仓股的mega信号给RiskCoordinator（驱动盘中止盈）
                    if sig.signal_type in ('mega_buy', 'mega_sell'):
                        try:
                            rc = getattr(self.container, 'risk_coordinator', None)
                            if rc and hasattr(rc, 'on_sniper_signal'):
                                rc.on_sniper_signal(sig.stock_code, sig.signal_type)
                        except Exception as e:
                            logger.debug(f"RiskCoordinator转发失败: {e}")

                if new_signals:
                    logger.info(
                        f"本次扫描产生 {len(new_signals)} 条信号, "
                        f"推送 {pushed} 条(TOP5: {[s['stock_name'] for s in self._top_ranking.get('opportunity', [])]})"
                    )

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
                'cooldown': {},      # signal_type -> last_trigger_time (HH:MM)
                'recent_signals': [],  # [(time_str, is_red)]
                'last_processed_index': -1,
            }

        state = self._stock_states[stock_code]
        signals = []

        # 只处理上次扫描以后的新数据点
        start_idx = max(state['last_processed_index'] + 1, 0)

        # 动态巨量阈值 — 基于每分钟平均净流入绝对值(而非总成交额)
        # 不同市值股票的net/turnover比差异大, 用avg_abs_net更公平
        abs_nets = [abs(p['net']) for p in timeline if p['net'] != 0]
        avg_abs_net = sum(abs_nets) / len(abs_nets) if abs_nets else avg_turnover
        dynamic_mega = max(mega_min, avg_abs_net * MEGA_MULTIPLIER)
        # 动态持续流出阈值
        dynamic_sustained = max(
            SUSTAINED_RATIO * avg_turnover * SUSTAINED_MINUTES,
            mega_min * 0.6,
        )

        for i in range(start_idx, len(timeline)):
            point = timeline[i]
            minute = point['time']  # HH:MM format
            is_scan_point = (i % SCAN_INTERVAL_MINUTES == 0 and i > 0)

            # --- 辅助函数 ---
            def _time_diff_minutes(t1: str, t2: str) -> int:
                """计算两个 HH:MM 时间差（分钟）"""
                h1, m1 = int(t1[:2]), int(t1[3:])
                h2, m2 = int(t2[:2]), int(t2[3:])
                return (h2 * 60 + m2) - (h1 * 60 + m1)

            def can_emit(sig_type: str, is_red: bool) -> bool:
                # 冷却检查 — 使用真实时间差而非索引
                if sig_type in state['cooldown']:
                    last_time = state['cooldown'][sig_type]
                    gap = _time_diff_minutes(last_time, minute)
                    if gap < COOLDOWN_MINUTES:
                        return False
                # 冲突检查 — 使用真实时间窗口
                for sig_time, r_is_red in state['recent_signals']:
                    gap = _time_diff_minutes(sig_time, minute)
                    if 0 <= gap < CONFLICT_WINDOW_MINUTES:
                        if (is_red and not r_is_red) or (not is_red and r_is_red):
                            return False
                return True

            def emit(sig_type: str, is_red: bool, detail: str, action: str):
                state['cooldown'][sig_type] = minute  # 记录真实时间
                state['recent_signals'].append((minute, is_red))
                # 清理过期记录（超过2倍冲突窗口）
                state['recent_signals'] = [
                    r for r in state['recent_signals']
                    if _time_diff_minutes(r[0], minute) < CONFLICT_WINDOW_MINUTES * 2
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
        """根据日成交额动态计算阈值(方案C: 混合动态)"""
        mega_floor = max(MEGA_FLOOR_MIN, day_total * MEGA_FLOOR_PCT)
        accel_min = mega_floor * 0.5   # accel阈值 = mega地板的一半
        reversal_min = mega_floor       # reversal阈值 = mega地板
        return accel_min, mega_floor, reversal_min

    # ==================== 强度评分 ====================

    def _calc_mega_buy_strength(
        self,
        stock_code: str,
        mult: float,
        timeline: List[dict],
        broker_acc_confidence: float = 0.0,
        broker_trap_confidence: float = 0.0,
        change_pct: float = 0.0,
    ) -> Tuple[int, str, str]:
        """计算 mega_buy 信号的综合强度评分 (0-100)

        Returns:
            (score, label, context_note)
            - score: 0-100 整数评分
            - label: "★★★ 强" 等标签
            - context_note: 多日上下文说明，如 "前2日连续砸盘后首日反弹"
        """
        score = 0.0
        context_parts = []

        # ========== 当日维度 (最高60分) ==========

        # 1. 净买入倍数 (最高30分)
        if mult >= 15:
            score += 30
        elif mult >= 8:
            score += 20
        elif mult >= 5:
            score += 10
        else:
            score += max(0, mult * 2)  # 低倍数给少量分

        # 2. 席位画像 (最高20分)
        if broker_acc_confidence > 0:
            # 吸筹确认：置信度 × 20
            score += min(20, broker_acc_confidence * 20)
        if broker_trap_confidence > 0:
            # 出货陷阱：扣分
            score -= min(10, broker_trap_confidence * 10)

        # 3. 当日累计资金流向 (最高10分)
        if timeline:
            cum_net = timeline[-1].get('cum_net', 0)
            if cum_net > 0:
                score += min(10, cum_net / 100)  # 每100万给1分，上限10
            elif cum_net < 0:
                score -= min(5, abs(cum_net) / 200)  # 累计为负轻微扣分

        # ========== 多日上下文维度 (最高40分) ==========

        # 4. 前N日信号模式 — 洗盘→反弹加成 (最高20分)
        prior_context = self._get_prior_days_context(stock_code, days=3)
        if prior_context:
            sell_ratio = prior_context.get('sell_signal_ratio', 0)
            prior_mega_sell_count = prior_context.get('mega_sell_count', 0)
            prior_sustained_out_count = prior_context.get('sustained_out_count', 0)
            prior_mega_buy_count = prior_context.get('mega_buy_count', 0)

            # 前几天以卖出信号为主（洗盘模式）
            if sell_ratio >= 0.7 and prior_mega_sell_count >= 2:
                score += 20
                context_parts.append(
                    f"前{prior_context['days_with_data']}日"
                    f"砸盘{prior_mega_sell_count}次+持续流出{prior_sustained_out_count}次"
                    f"→今日首次反弹"
                )
            elif sell_ratio >= 0.5:
                score += 10
                context_parts.append(f"前几日空方偏多(卖出占{sell_ratio:.0%})")

            # 如果前几天也有大量 mega_buy，说明持续建仓
            if prior_mega_buy_count >= 3:
                score += 5
                context_parts.append(f"连续多日出现建仓信号(共{prior_mega_buy_count}次)")

        # 5. 当日连续 mega_buy 加成 (最高10分)
        today_mega_buy_count = sum(
            1 for s in self._today_signals
            if s.stock_code == stock_code and s.signal_type == 'mega_buy'
        )
        if today_mega_buy_count >= 3:
            score += 10
            context_parts.append(f"今日第{today_mega_buy_count + 1}次巨量抢筹")
        elif today_mega_buy_count >= 1:
            score += 5
            context_parts.append(f"今日第{today_mega_buy_count + 1}次巨量抢筹")

        # 6. 价格位置 (最高10分)
        if timeline and len(timeline) >= 5:
            prices = [p['price'] for p in timeline if p['price'] > 0]
            if prices:
                cur = prices[-1]
                # 用近5日高低点（如果有prior_context的话）
                hi = prior_context.get('price_high', max(prices)) if prior_context else max(prices)
                lo = prior_context.get('price_low', min(prices)) if prior_context else min(prices)
                if hi > lo:
                    pos = max(0.0, min(1.0, (cur - lo) / (hi - lo)))
                    if pos < 0.3:
                        score += 10
                        context_parts.append(f"价格处于近期低位({pos:.0%})")
                    elif pos < 0.5:
                        score += 5
                    elif pos > 0.8:
                        score -= 5
                        context_parts.append(f"价格处于近期高位({pos:.0%})")

        # ========== 最终裁定 ==========
        final_score = max(0, min(100, int(score)))

        if final_score >= 81:
            label = "★★★★ 极强"
        elif final_score >= 61:
            label = "★★★ 强"
        elif final_score >= 31:
            label = "★★ 中"
        else:
            label = "★ 弱"

        context_note = "；".join(context_parts) if context_parts else ""
        return final_score, label, context_note

    def _get_prior_days_context(self, stock_code: str, days: int = 3) -> Optional[dict]:
        """查询前N个交易日的 sniper_signals 统计，用于多日上下文判断"""
        db = getattr(self.container, 'db_manager', None)
        if not db:
            return None

        today = date.today().isoformat()
        try:
            rows = db.execute_query(
                """SELECT signal_type, price, trade_date
                   FROM sniper_signals
                   WHERE stock_code = ?
                   AND trade_date < ?
                   AND trade_date >= date(?, '-' || ? || ' days')
                   ORDER BY trade_date, id""",
                (stock_code, today, today, str(days))
            )
            if not rows:
                return None

            sell_types = {'mega_sell', 'sustained_out', 'reversal_bear'}
            buy_types = {'mega_buy', 'accel_in', 'reversal_bull'}

            sell_count = sum(1 for r in rows if r[0] in sell_types)
            buy_count = sum(1 for r in rows if r[0] in buy_types)
            total = sell_count + buy_count
            if total == 0:
                return None

            prices = [float(r[1]) for r in rows if r[1] and float(r[1]) > 0]
            dates_set = {r[2] for r in rows}

            return {
                'sell_signal_ratio': sell_count / total,
                'mega_sell_count': sum(1 for r in rows if r[0] == 'mega_sell'),
                'sustained_out_count': sum(1 for r in rows if r[0] == 'sustained_out'),
                'mega_buy_count': sum(1 for r in rows if r[0] == 'mega_buy'),
                'price_high': max(prices) if prices else 0,
                'price_low': min(prices) if prices else 0,
                'days_with_data': len(dates_set),
                'total_signals': total,
            }
        except Exception as e:
            logger.debug(f"查询前N日信号上下文失败: {stock_code}: {e}")
            return None

    # ==================== DB 持久化 ====================

    def _save_signal_to_db(self, signal: SniperSignal):
        """将信号保存到数据库（去重: 同日同股同类型同分钟只保留一条）"""
        db = getattr(self.container, 'db_manager', None)
        if not db:
            return
        try:
            today = date.today().isoformat()
            # 先检查是否已存在相同信号（防止重启导致重复）
            existing = db.execute_query(
                '''SELECT id FROM sniper_signals
                   WHERE trade_date = ? AND stock_code = ? AND signal_type = ? AND time = ?
                   LIMIT 1''',
                (today, signal.stock_code, signal.signal_type, signal.time)
            )
            if existing:
                # 已存在，用最新的信息更新（强度评分可能更完整）
                db.execute_update(
                    '''UPDATE sniper_signals
                       SET detail = ?, severity = ?, strength = ?, price = ?
                       WHERE trade_date = ? AND stock_code = ? AND signal_type = ? AND time = ?
                       AND id = ?''',
                    (signal.detail, signal.severity, signal.strength, signal.price,
                     today, signal.stock_code, signal.signal_type, signal.time,
                     existing[0][0])
                )
                return
            db.execute_insert(
                '''INSERT INTO sniper_signals
                   (trade_date, time, stock_code, stock_name, signal_type,
                    is_red, price, detail, action, severity, strength)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (today, signal.time, signal.stock_code, signal.stock_name,
                 signal.signal_type, signal.is_red, signal.price,
                 signal.detail, signal.action, signal.severity, signal.strength)
            )
        except Exception as e:
            logger.debug(f"保存信号到DB失败: {e}")

    def _load_today_signals_from_db(self):
        """启动时从DB加载今日信号"""
        db = getattr(self.container, 'db_manager', None)
        if not db:
            return
        try:
            today = date.today().isoformat()
            rows = db.execute_query(
                '''SELECT time, stock_code, stock_name, signal_type, is_red,
                          price, detail, action, severity,
                          COALESCE(strength, 0) as strength
                   FROM sniper_signals
                   WHERE trade_date = ?
                   ORDER BY id ASC''',
                (today,)
            )
            for r in rows:
                strength_val = int(r[9]) if len(r) > 9 and r[9] else 0
                # 从 strength 值推导 label
                if strength_val >= 81:
                    s_label = "★★★★ 极强"
                elif strength_val >= 61:
                    s_label = "★★★ 强"
                elif strength_val >= 31:
                    s_label = "★★ 中"
                elif strength_val > 0:
                    s_label = "★ 弱"
                else:
                    s_label = ""
                self._today_signals.append(SniperSignal(
                    time=r[0], stock_code=r[1], stock_name=r[2],
                    signal_type=r[3], is_red=bool(r[4]), price=float(r[5] or 0),
                    detail=r[6] or '', action=r[7] or '', severity=r[8] or 'high',
                    strength=strength_val, strength_label=s_label,
                ))
                # 恢复冷却状态（防止重启后重复检测同一分钟的信号）
                sig_time = r[0]   # HH:MM
                sig_code = r[1]
                sig_type = r[3]
                sig_is_red = bool(r[4])
                if sig_code not in self._stock_states:
                    self._stock_states[sig_code] = {
                        'prev_cum_direction': 'neutral',
                        'cooldown': {},
                        'recent_signals': [],
                        'last_processed_index': -1,
                    }
                st = self._stock_states[sig_code]
                # 用最新的信号时间更新冷却记录
                if sig_type not in st['cooldown'] or sig_time > st['cooldown'][sig_type]:
                    st['cooldown'][sig_type] = sig_time
                st['recent_signals'].append((sig_time, sig_is_red))
        except Exception as e:
            logger.warning(f"从DB加载今日信号失败: {e}")

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

        # 3. 通知统一决策引擎
        try:
            engine = getattr(self.container, 'trade_decision_engine', None)
            if engine:
                await engine.on_sniper_signal(signal)
        except Exception as e:
            logger.warning(f"决策引擎通知失败: {e}", exc_info=True)

    # ==================== 双窗口评分排行 ====================

    def _update_ranking(self, conn, watch_codes: list, today: str):
        """每次扫描后更新 TOP 排行榜（双窗口: 3m+30m）

        整合改进: 使用 strength 细粒度评分替代固定 SIGNAL_WEIGHTS
        - 机会榜: 用窗口内绿灯信号的最高 strength
        - 风险榜: 用窗口内红灯信号的最高 strength
        """
        now_str = datetime.now().strftime("%H:%M")

        opp_scores = []
        risk_scores = []

        for code in watch_codes:
            tl, avg_tv, day_total = self._load_minute_data(conn, code, today)
            if len(tl) < 2 or day_total < MIN_DAILY_TURNOVER:
                continue

            open_price = tl[0]['price']
            cur_price = tl[-1]['price']
            if open_price <= 0 or cur_price <= 0:
                continue

            chg_now = round((cur_price - open_price) / open_price * 100, 2)
            stock_name = self._get_stock_name(conn, code)

            # 获取该股票的今日信号
            stock_sigs = [s for s in self._today_signals if s.stock_code == code]

            # 对两个窗口分别计算，取 max
            best_opp = 0.0
            best_risk = 0.0
            best_opp_detail = {}
            best_risk_detail = {}

            for w_size, f_thresh, c_thresh in [
                (SCORE_SHORT_WINDOW, SCORE_SHORT_FLOW_THRESH, SCORE_SHORT_CHG_THRESH),
                (SCORE_LONG_WINDOW, SCORE_LONG_FLOW_THRESH, SCORE_LONG_CHG_THRESH),
            ]:
                # 动态窗口：当交易时间<10分钟时，动态切换为3分钟窗口
                actual_w_size = 3 if len(tl) < 10 else w_size

                # 窗口数据
                window = [p for p in tl if p['time'] > self._sub_minutes(now_str, actual_w_size)]
                if len(window) < 2:
                    continue

                w_net = sum(p['net'] for p in window)
                w_chg = round(
                    (window[-1]['price'] - window[0]['price']) / window[0]['price'] * 100, 2
                ) if window[0]['price'] > 0 else 0.0

                # 窗口内信号 — 改用 strength 最高值
                w_cutoff = self._sub_minutes(now_str, actual_w_size)
                w_sigs = [s for s in stock_sigs if s.time > w_cutoff]

                # 绿灯信号: 取最高 strength (0-100)
                green_strengths = [s.strength for s in w_sigs if not s.is_red and s.strength > 0]
                max_green_strength = max(green_strengths) if green_strengths else 0

                # 红灯信号: 取最高 strength
                red_strengths = [s.strength for s in w_sigs if s.is_red and s.strength > 0]
                max_red_strength = max(red_strengths) if red_strengths else 0

                avg_w_tv = sum(p['turnover'] for p in window) / len(window) if window else 1

                # 🟢 机会分
                if w_net > f_thresh or w_chg > c_thresh or max_green_strength > 0:
                    opp_flow = min((max(w_net, 0) / avg_w_tv) * 5, 50) if avg_w_tv > 0 else 0
                    opp_mom = min(max(w_chg, 0) * 3, 40)

                    # 共振加分（回测验证）
                    has_mega = any(s.signal_type == 'mega_buy' and not s.is_red for s in w_sigs)
                    has_accel = any(s.signal_type == 'accel_in' and not s.is_red for s in w_sigs)
                    combo_bonus = 15 if (has_mega and has_accel) else 0

                    # 多重mega加分（回测80%胜率）
                    mega_count = sum(1 for s in w_sigs if s.signal_type == 'mega_buy' and not s.is_red)
                    multi_mega_bonus = 20 if mega_count >= 2 else 0

                    # 多重accel_in加分（仅在有mega_buy时生效）
                    accel_count = sum(1 for s in w_sigs if s.signal_type == 'accel_in' and not s.is_red)
                    multi_accel_bonus = min(accel_count - 1, 3) * 5 if (has_mega and accel_count >= 2) else 0

                    # 新公式: 信号质量(strength)×0.6 + 资金流×0.2 + 动量×0.2 + 加成
                    signal_quality = max_green_strength  # 0-100
                    opp_total = (signal_quality * 0.6 + opp_flow * 0.2 + opp_mom * 0.2
                                 + combo_bonus + multi_mega_bonus + multi_accel_bonus)
                    if opp_total > best_opp:
                        best_opp = opp_total
                        best_opp_detail = {
                            'window': actual_w_size, 'flow': round(opp_flow, 1),
                            'momentum': round(opp_mom, 1),
                            'signal': round(signal_quality, 1),  # 改为 strength
                            'strength_max': round(max_green_strength, 1),  # 新增字段
                            'w_net': round(w_net), 'w_chg': round(w_chg, 2),
                            'combo': combo_bonus, 'multi_mega': multi_mega_bonus,
                            'multi_accel': multi_accel_bonus,
                        }

                # 🔴 风险分
                if w_net < -f_thresh or w_chg < -c_thresh or max_red_strength > 0:
                    risk_flow = min((max(-w_net, 0) / avg_w_tv) * 5, 50) if avg_w_tv > 0 else 0
                    risk_mom = min(max(-w_chg, 0) * 3, 40)

                    # 新公式: 风险信号质量×0.6 + 流出×0.2 + 跌幅×0.2
                    risk_quality = max_red_strength  # 0-100
                    risk_total = risk_quality * 0.6 + risk_flow * 0.2 + risk_mom * 0.2
                    if risk_total > best_risk:
                        best_risk = risk_total
                        best_risk_detail = {
                            'window': actual_w_size, 'flow': round(risk_flow, 1),
                            'momentum': round(risk_mom, 1),
                            'signal': round(risk_quality, 1),  # 改为 strength
                            'strength_max': round(max_red_strength, 1),  # 新增字段
                            'w_net': round(w_net), 'w_chg': round(w_chg, 2),
                        }

            if best_opp > 5:
                opp_scores.append({
                    'stock_code': code, 'stock_name': stock_name,
                    'score': round(best_opp, 1), 'chg': chg_now,
                    'detail': best_opp_detail,
                })
            if best_risk > 5:
                risk_scores.append({
                    'stock_code': code, 'stock_name': stock_name,
                    'score': round(best_risk, 1), 'chg': chg_now,
                    'detail': best_risk_detail,
                })

        opp_scores.sort(key=lambda x: -x['score'])
        risk_scores.sort(key=lambda x: -x['score'])

        self._top_ranking = {
            'opportunity': opp_scores[:5],
            'risk': risk_scores[:5],
            'updated_at': now_str,
        }

        if opp_scores or risk_scores:
            opp_names = ', '.join(f"{s['stock_name']}({s['score']})" for s in opp_scores[:5])
            risk_names = ', '.join(f"{s['stock_name']}({s['score']})" for s in risk_scores[:5])
            logger.info(f"排行更新 🟢机会[{opp_names}] 🔴风险[{risk_names}]")

    @staticmethod
    def _sub_minutes(hhmm: str, mins: int) -> str:
        """时间减去N分钟"""
        h, m = int(hhmm[:2]), int(hhmm[3:])
        total = h * 60 + m - mins
        if total < 0:
            total = 0
        return f"{total // 60:02d}:{total % 60:02d}"
