#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
日内价格位置实时策略

基于回测最优参数，实时监控股价是否到达买卖点。
当监控股票池中的股票进入候选时，按需触发回测分析并缓存参数；
实时行情到达回测得出的买卖点时，产生交易信号。

辅助函数（目标价计算、开盘类型判断等）见 pp_live_helpers.py。
"""

import logging
from datetime import datetime
from typing import Dict, Any, List, Optional

from .base_strategy import (
    BaseStrategy, StrategyResult, ConditionDetail, TradingConditionResult,
)
from .strategy_registry import register_strategy
from .pp_live_helpers import (
    DEFAULT_ZONE, classify_open_type, calc_targets,
    select_param_and_anchor, build_condition_details,
)
from ..services.trading.price_position.pp_live_models import (
    CachedAnalysisParams, LiveTradeTargets,
)


@register_strategy("price_position_live", is_default=False)
class PricePositionLiveStrategy(BaseStrategy):
    """
    日内价格位置实时策略

    核心逻辑：
    1. 从 ParamsCacheManager 获取回测最优参数
    2. 根据开盘类型（高开/平开/低开）选择锚点和参数
    3. 计算当日买卖目标价
    4. 对比实时价格判断是否触发信号
    """

    STRATEGY_ID = "price_position_live"
    IS_DEFAULT = False

    def __init__(self, data_service=None, config: Dict[str, Any] = None):
        super().__init__(data_service, config)
        self._params_cache = None  # ParamsCacheManager，由服务层注入
        self._daily_targets: Dict[str, LiveTradeTargets] = {}

    @property
    def name(self) -> str:
        return "日内价格位置策略"

    @property
    def description(self) -> str:
        return "基于回测最优参数，监控股价到达买卖点时产生信号"

    def set_params_cache(self, cache):
        """注入参数缓存管理器"""
        self._params_cache = cache

    def get_buy_conditions(self) -> List[str]:
        return ["股票已完成价格位置回测分析", "当前价格 <= 回测最优买入目标价"]

    def get_sell_conditions(self) -> List[str]:
        return ["当前价格 >= 回测最优卖出目标价", "或当前价格 <= 止损价"]

    def get_required_kline_days(self) -> int:
        return 0

    def check_signals(
        self, stock_code: str, quote_data: Dict[str, Any],
        kline_data: List[Dict[str, Any]],
    ) -> StrategyResult:
        """检查交易信号（核心方法）"""
        result = StrategyResult(stock_code=stock_code)
        last_price = quote_data.get('last_price', 0)
        open_price = quote_data.get('open_price', 0)

        if not last_price or not open_price:
            return result

        cached = self._get_cached_params(stock_code)
        if not cached:
            return result

        targets = self._get_or_calc_targets(stock_code, cached, last_price, open_price)
        if not targets:
            return result

        strategy_data = {'targets': targets.to_dict(), 'last_price': last_price}

        if last_price <= targets.stop_price:
            result.sell_signal = True
            result.sell_reason = f"触发止损: 现价{last_price} <= 止损价{targets.stop_price}"
            result.signal_strength = 0.9
            strategy_data['trigger'] = 'stop_loss'
        elif last_price <= targets.buy_target:
            result.buy_signal = True
            result.buy_reason = (
                f"到达买入点: 现价{last_price} <= 目标{targets.buy_target} "
                f"({targets.open_type}, 锚点{targets.anchor_price})"
            )
            result.signal_strength = 0.8
            strategy_data['trigger'] = 'buy'
        elif last_price >= targets.sell_target:
            result.sell_signal = True
            result.sell_reason = f"到达卖出点: 现价{last_price} >= 目标{targets.sell_target}"
            result.signal_strength = 0.7
            strategy_data['trigger'] = 'profit'

        result.strategy_data = strategy_data
        return result

    # ==================== 重写基类方法 ====================

    def check_stock_conditions(self, stock_data: tuple) -> TradingConditionResult:
        """重写基类方法，跳过K线获取（参数来自缓存）"""
        stock_id, code, name, price, change_pct, volume, high, low, open_price, plate = stock_data

        result = TradingConditionResult(
            stock_code=code, stock_name=name or "",
            plate_name=plate or "", strategy_name=self.name,
        )

        if not high or not low or not open_price:
            result.reason = "缺少价格数据"
            return result

        quote_data = {
            'code': code, 'last_price': price, 'high_price': high,
            'low_price': low, 'open_price': open_price,
            'change_percent': change_pct, 'volume': volume,
        }

        try:
            strategy_result = self.check_signals(code, quote_data, [])
            result.strategy_result = strategy_result
            result.condition_passed = strategy_result.has_signal
            result.details = build_condition_details(strategy_result, quote_data)

            if strategy_result.buy_signal:
                result.reason = f"✅ 买入信号触发: {strategy_result.buy_reason}"
            elif strategy_result.sell_signal:
                result.reason = f"✅ 卖出信号触发: {strategy_result.sell_reason}"
            else:
                result.reason = self._build_no_signal_reason(code)
        except Exception as e:
            result.reason = f"策略检查异常: {e}"
            logging.error(f"[价格位置实时] {code} 检查异常: {e}")

        return result

    def validate_data(self, quote_data, kline_data) -> tuple:
        """不需要K线数据验证"""
        if not quote_data:
            return False, "缺少实时报价数据"
        return True, ""

    def clear_daily_targets(self):
        """清除当日目标价缓存（每日收盘后调用）"""
        self._daily_targets.clear()

    # ==================== 私有方法 ====================

    def _get_cached_params(self, stock_code: str) -> Optional[CachedAnalysisParams]:
        """获取缓存参数，无缓存时触发异步分析"""
        if not self._params_cache:
            return None
        cached = self._params_cache.get_params(stock_code)
        if cached:
            return cached
        if not self._params_cache.is_pending(stock_code):
            self._params_cache.request_analysis(stock_code)
        return None

    def _get_or_calc_targets(
        self, stock_code: str, cached: CachedAnalysisParams,
        last_price: float, open_price: float,
    ) -> Optional[LiveTradeTargets]:
        """获取或计算当日目标价（每只股票每天只计算一次）"""
        existing = self._daily_targets.get(stock_code)
        if existing and existing.open_price == open_price:
            return existing

        prev_close = self._estimate_prev_close(stock_code, open_price)
        open_type = classify_open_type(open_price, prev_close, cached.gap_threshold)

        param, anchor_price = select_param_and_anchor(
            cached, open_type, open_price, prev_close,
        )
        if not param:
            return None

        buy_target, sell_target, stop_price = calc_targets(anchor_price, param)

        targets = LiveTradeTargets(
            stock_code=stock_code, zone=DEFAULT_ZONE, open_type=open_type,
            anchor_price=anchor_price, prev_close=prev_close, open_price=open_price,
            buy_target=buy_target, sell_target=sell_target, stop_price=stop_price,
            buy_dip_pct=param.buy_dip_pct, sell_rise_pct=param.sell_rise_pct,
            stop_loss_pct=param.stop_loss_pct, calculated_at=datetime.now().isoformat(),
        )
        self._daily_targets[stock_code] = targets

        logging.info(
            f"[价格位置实时] {stock_code} 目标价已计算: "
            f"开盘类型={open_type}, 锚点={anchor_price}, "
            f"买入={buy_target}, 卖出={sell_target}, 止损={stop_price}"
        )
        return targets

    def _estimate_prev_close(self, stock_code: str, open_price: float) -> float:
        """估算前收盘价"""
        existing = self._daily_targets.get(stock_code)
        if existing and existing.prev_close > 0:
            return existing.prev_close
        return open_price

    def _build_no_signal_reason(self, stock_code: str) -> str:
        """构建无信号时的原因说明"""
        if not self._params_cache:
            return "❌ 参数缓存未初始化"
        if self._params_cache.is_pending(stock_code):
            return "⏳ 回测分析进行中..."
        cached = self._params_cache.get_params(stock_code)
        if not cached:
            return "❌ 无回测参数，已触发分析"
        targets = self._daily_targets.get(stock_code)
        if targets:
            return (
                f"❌ 未触发信号 (买入<={targets.buy_target}, "
                f"卖出>={targets.sell_target})"
            )
        return "❌ 无交易信号"
