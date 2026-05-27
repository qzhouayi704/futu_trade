#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
资金流向信号引擎

协调所有规则检查器，基于实时行情 + 资金流向数据生成买卖信号。
由 QuotePipeline.run_monitoring_cycle() 每60秒调用一次。
"""

import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from .flow_signal_models import FlowSignal, RuleContext
from .flow_signal_rules import ALL_RULES, BaseFlowRule


logger = logging.getLogger("capital_flow.engine")


class CapitalFlowSignalEngine:
    """资金流向信号引擎 — 基于操盘规则生成买卖信号"""

    def __init__(
        self,
        capital_flow_analyzer=None,
        db_manager=None,
        vwap_service=None,
        futu_client=None,
        momentum_analyzer=None,
    ):
        """
        初始化信号引擎

        Args:
            capital_flow_analyzer: 资金流向分析器(CapitalFlowAnalyzer)
            db_manager: 数据库管理器
            vwap_service: VWAP服务(可选，用于均价线规则)
            momentum_analyzer: 5分钟动量分析器(Momentum5MinAnalyzer，可选)
        """
        self._analyzer = capital_flow_analyzer
        self._db = db_manager
        self._vwap_service = vwap_service
        self._momentum_analyzer = momentum_analyzer


        # 实例化所有规则
        self._rules: List[BaseFlowRule] = [RuleCls() for RuleCls in ALL_RULES]

        # VWAP跌破追踪 {stock_code: first_break_time}
        self._vwap_break_tracker: Dict[str, float] = {}

        # 前日涨跌幅缓存 {stock_code: change_pct}
        self._prev_day_cache: Dict[str, float] = {}
        self._prev_day_cache_date: str = ""

        # 日均成交额缓存 {stock_code: amount}
        self._avg_turnover_cache: Dict[str, float] = {}

        # 信号记录表初始化标记
        self._table_ensured = False

        logger.info(
            f"资金流向信号引擎初始化完成，加载 {len(self._rules)} 条规则: "
            + ", ".join(f"[{r.rule_id}]{r.rule_name}" for r in self._rules)
        )

    def check_signals(
        self,
        quotes: List[Dict[str, Any]],
        positions: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """
        主检查入口 — 每个监控周期调用一次

        Args:
            quotes: 实时报价列表
            positions: 持仓字典 {stock_code: position_info}

        Returns:
            trade_action 格式的信号列表
        """
        if not quotes:
            return []

        self._ensure_table()

        # 批量获取资金流数据（带缓存）
        stock_codes = [q.get('code', '') for q in quotes if q.get('code')]
        capital_flows = self._fetch_capital_flows(stock_codes)

        # 批量获取5分钟动量数据
        momentum_map = {}
        if self._momentum_analyzer:
            try:
                momentum_map = self._momentum_analyzer.analyze_batch(stock_codes)
            except Exception as e:
                logger.debug(f"[信号引擎] 动量分析批量失败: {e}")

        results: List[Dict[str, Any]] = []
        seen_codes: set = set()

        for quote in quotes:
            code = quote.get('code', '')
            if not code or code in seen_codes:
                continue
            seen_codes.add(code)

            try:
                ctx = self._build_context(quote, positions, capital_flows, momentum_map)
                if ctx is None:
                    continue

                for rule in self._rules:
                    signal = rule.check(ctx)
                    if signal:
                        results.append(signal.to_trade_action())
                        self._save_signal(signal)
            except Exception as e:
                logger.debug(f"[信号引擎] {code} 规则检查异常: {e}")

        # 同步资金流数据到换票引擎
        self._sync_to_rotator(quotes, capital_flows, positions)

        if results:
            logger.info(f"[信号引擎] 本轮产生 {len(results)} 个信号")

        return results

    def _build_context(
        self,
        quote: Dict[str, Any],
        positions: Dict[str, Any],
        capital_flows: Dict[str, dict],
        momentum_map: Dict = None,
    ) -> Optional[RuleContext]:
        """构建规则评估上下文"""
        code = quote.get('code', '')
        current_price = quote.get('last_price', 0) or quote.get('current_price', 0)
        prev_close = quote.get('prev_close', 0)

        if current_price <= 0 or prev_close <= 0:
            return None

        change_pct = (current_price - prev_close) / prev_close * 100

        # 资金流数据
        flow = capital_flows.get(code)
        main_net_inflow = 0.0
        net_inflow_ratio = 0.0
        if flow:
            main_net_inflow = flow.get('main_net_inflow', 0)
            net_inflow_ratio = flow.get('net_inflow_ratio', 0)

        # 资金流历史（从DB缓存读取）
        flow_history = self._get_flow_history(code)

        # VWAP
        vwap = self._get_vwap(code)

        # VWAP跌破追踪
        vwap_break_minutes = 0
        if vwap and vwap > 0 and current_price < vwap:
            if code not in self._vwap_break_tracker:
                self._vwap_break_tracker[code] = time.time()
            elapsed = time.time() - self._vwap_break_tracker[code]
            vwap_break_minutes = int(elapsed / 60)
        else:
            self._vwap_break_tracker.pop(code, None)

        # 前日涨跌幅
        prev_day_change = self._get_prev_day_change(code)

        # 日均成交额
        avg_turnover = self._get_avg_daily_turnover(code)

        # K线位置（趋势联动）
        kline_position = self._get_kline_position(code, current_price)

        # 持仓状态
        pos = positions.get(code)
        has_position = pos is not None and pos.get('qty', 0) > 0

        # 5分钟动量（新增）
        momentum_kwargs = {}
        if momentum_map:
            snap = momentum_map.get(code)
            if snap:
                momentum_kwargs = {
                    'momentum_direction': snap.momentum_direction,
                    'momentum_strength': snap.momentum_strength,
                    'momentum_acceleration': snap.momentum_acceleration,
                    'momentum_trend': snap.momentum_trend,
                    'has_top_pattern': snap.has_top_pattern,
                    'has_bottom_pattern': snap.has_bottom_pattern,
                    'upper_shadow_warning': snap.upper_shadow_warning,
                    'lower_shadow_support': snap.lower_shadow_support,
                }

        # 流动性：从 quote 中获取 spread_pct
        spread_pct = quote.get('spread_pct', 0.0) or 0.0

        # 交易阶段
        trading_phase = self._get_trading_phase()

        return RuleContext(
            stock_code=code,
            stock_name=quote.get('name', code),
            current_price=current_price,
            prev_close=prev_close,
            open_price=quote.get('open_price', 0),
            high_price=quote.get('high_price', 0),
            low_price=quote.get('low_price', 0),
            change_pct=change_pct,
            volume=quote.get('volume', 0),
            turnover=quote.get('turnover', 0),
            capital_flow=flow,
            main_net_inflow=main_net_inflow,
            net_inflow_ratio=net_inflow_ratio,
            capital_flow_history=flow_history,
            vwap=vwap,
            prev_day_change_pct=prev_day_change,
            avg_daily_turnover=avg_turnover,
            vwap_break_minutes=vwap_break_minutes,
            kline_position=kline_position,
            has_position=has_position,
            position_qty=pos.get('qty', 0) if pos else 0,
            spread_pct=spread_pct,
            trading_phase=trading_phase,
            **momentum_kwargs,
        )


    @staticmethod
    def _get_trading_phase() -> str:
        """获取当前交易阶段（轻量版，不依赖 TradingPhaseManager）"""
        from datetime import datetime
        t = datetime.now().strftime('%H:%M')
        if t < '09:30':
            return 'pre_market'
        elif t < '09:40':
            return 'phase1_opening'
        elif t < '10:00':
            return 'phase2_observe'
        elif t < '12:00':
            return 'phase3_rotate'
        elif t < '13:00':
            return 'lunch_break'
        elif t < '16:00':
            return 'phase3_rotate'
        else:
            return 'after_hours'

    # ========== 数据获取 ==========

    def _fetch_capital_flows(self, stock_codes: List[str]) -> Dict[str, dict]:
        """批量读取资金流缓存数据（纯读取，不调 API）

        资金流数据由 HighTurnoverEnricher 后台预填充，此处只消费缓存。
        """
        if not self._analyzer or not stock_codes:
            return {}
        try:
            return self._analyzer.batch_read_cache_only(stock_codes)
        except Exception as e:
            logger.debug(f"读取资金流缓存失败: {e}")
            return {}

    def _get_flow_history(self, stock_code: str) -> List[dict]:
        """获取近5日资金流历史（从DB读取，不调API）"""
        if not self._db:
            return []
        try:
            rows = self._db.execute_query("""
                SELECT date, net_inflow, net_inflow_ratio
                FROM capital_flow_daily
                WHERE stock_code = ? ORDER BY date DESC LIMIT 5
            """, (stock_code,))
            if not rows:
                return []
            return [
                {'date': r[0], 'net_inflow': r[1], 'net_inflow_ratio': r[2]}
                for r in rows
            ]
        except Exception:
            return []

    def _get_vwap(self, stock_code: str) -> Optional[float]:
        """获取当日VWAP"""
        if not self._vwap_service:
            return None
        try:
            cache = getattr(self._vwap_service, '_cache', {})
            vwap_data = cache.get(stock_code)
            if vwap_data and vwap_data.get('vwap', 0) > 0:
                return vwap_data['vwap']
        except Exception:
            pass
        return None

    def _get_prev_day_change(self, stock_code: str) -> Optional[float]:
        """获取前日涨跌幅(从DB kline_data读取)

        日线级别数据必须排除当天未完成的K线，只使用已收盘的完整交易日。
        rows[0] = 最近完成交易日(即"前日"), rows[1] = 再前一天
        前日涨跌幅 = (rows[0] - rows[1]) / rows[1] * 100
        """
        today = datetime.now().strftime('%Y-%m-%d')
        if self._prev_day_cache_date != today:
            self._prev_day_cache.clear()
            self._prev_day_cache_date = today

        if stock_code in self._prev_day_cache:
            return self._prev_day_cache[stock_code]

        if not self._db:
            return None
        try:
            rows = self._db.execute_query("""
                SELECT close_price FROM kline_data
                WHERE stock_code = ? AND date(time_key) < ?
                ORDER BY time_key DESC LIMIT 2
            """, (stock_code, today))
            if rows and len(rows) >= 2 and rows[1][0] and rows[1][0] > 0:
                # rows[0] = 最近完成交易日, rows[1] = 再前一天
                change = (rows[0][0] - rows[1][0]) / rows[1][0] * 100
                self._prev_day_cache[stock_code] = change
                return change
        except Exception:
            pass
        return None

    def _get_avg_daily_turnover(self, stock_code: str) -> float:
        """获取近5日日均成交额（排除当天未完成数据）"""
        if stock_code in self._avg_turnover_cache:
            return self._avg_turnover_cache[stock_code]

        if not self._db:
            return 0
        try:
            today = datetime.now().strftime('%Y-%m-%d')
            rows = self._db.execute_query("""
                SELECT AVG(turnover) FROM (
                    SELECT turnover FROM kline_data
                    WHERE stock_code = ? AND date(time_key) < ?
                    ORDER BY time_key DESC LIMIT 5
                )
            """, (stock_code, today))
            if rows and rows[0][0]:
                val = float(rows[0][0])
                self._avg_turnover_cache[stock_code] = val
                return val
        except Exception:
            pass
        return 0

    def _get_kline_position(self, stock_code: str, current_price: float) -> float | None:
        """计算当前价格在近20日K线范围内的位置 (0=最低, 1=最高)"""
        if not self._db or current_price <= 0:
            return None
        try:
            rows = self._db.execute_query("""
                SELECT high_price, low_price FROM kline_data
                WHERE stock_code = ?
                ORDER BY time_key DESC LIMIT 20
            """, (stock_code,))
            if not rows or len(rows) < 5:
                return None
            highs = [r[0] for r in rows if r[0]]
            lows = [r[1] for r in rows if r[1]]
            if not highs or not lows:
                return None
            h, l = max(highs), min(lows)
            if h <= l:
                return 0.5
            return round((current_price - l) / (h - l), 3)
        except Exception:
            return None

    # ========== 信号持久化 ==========

    def _ensure_table(self):
        """确保信号记录表存在"""
        if self._table_ensured or not self._db:
            return
        try:
            self._db.execute_update("""
                CREATE TABLE IF NOT EXISTS capital_flow_signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    rule_id VARCHAR(10) NOT NULL,
                    rule_name VARCHAR(50) NOT NULL,
                    stock_code VARCHAR(20) NOT NULL,
                    stock_name VARCHAR(50),
                    signal_type VARCHAR(10) NOT NULL,
                    price DECIMAL(10,3),
                    reason TEXT,
                    confidence DECIMAL(3,2),
                    priority VARCHAR(10),
                    action_suggestion TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            self._table_ensured = True
        except Exception as e:
            logger.warning(f"创建信号表失败: {e}")

    def _save_signal(self, signal: FlowSignal):
        """保存信号到DB（写入前检查冷却期内是否已有相同记录）"""
        if not self._db:
            return
        try:
            # 检查当天是否已有相同 stock+rule 的记录
            existing = self._db.execute_query("""
                SELECT COUNT(*) FROM capital_flow_signals
                WHERE stock_code = ? AND rule_id = ?
                  AND date(created_at) = date('now')
            """, (signal.stock_code, signal.rule_id))

            if existing and existing[0][0] > 0:
                return  # 当天已有记录，跳过

            self._db.execute_update("""
                INSERT INTO capital_flow_signals
                (rule_id, rule_name, stock_code, stock_name,
                 signal_type, price, reason, confidence,
                 priority, action_suggestion)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                signal.rule_id, signal.rule_name,
                signal.stock_code, signal.stock_name,
                signal.signal_type, signal.price,
                signal.reason, signal.confidence,
                signal.priority, signal.action_suggestion,
            ))
        except Exception as e:
            logger.debug(f"保存信号失败: {e}")

    # ========== API查询 ==========

    def get_status(self) -> Dict[str, Any]:
        """返回引擎状态（供API查询）"""
        return {
            'enabled': True,
            'rules_count': len(self._rules),
            'rules': [
                {'id': r.rule_id, 'name': r.rule_name, 'cooldown': r.cooldown}
                for r in self._rules
            ],
            'vwap_tracking': len(self._vwap_break_tracker),
        }

    def _sync_to_rotator(
        self,
        quotes: List[Dict[str, Any]],
        capital_flows: Dict[str, Dict[str, Any]],
        positions: Dict[str, Any],
    ):
        """将实时资金流数据同步到 CapitalFlowRotator"""
        try:
            from ....dependencies import get_container
            try:
                container = get_container()
            except Exception:
                return

            rotator = container.capital_flow_rotator
            scorer = container.stock_scorer
            if not rotator:
                return

            held_codes = set(positions.keys()) if positions else set()

            for quote in quotes:
                code = quote.get('code', '')
                if not code:
                    continue

                flow = capital_flows.get(code, {})
                net_inflow = flow.get('main_net_inflow', 0)
                net_ratio = flow.get('net_inflow_ratio', 0)

                # 获取评分
                score = 0
                if scorer:
                    cached = scorer.get_score(code)
                    score = cached.total_score if cached else 0

                rotator.update_flow(
                    stock_code=code,
                    stock_name=quote.get('name', ''),
                    net_inflow=net_inflow,
                    net_inflow_ratio=net_ratio,
                    score=score,
                    is_held=code in held_codes,
                )

        except Exception as e:
            logger.debug(f"[信号引擎] 同步到换票引擎失败: {e}")

