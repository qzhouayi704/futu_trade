#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
日内价格位置策略 - 数据模型

纯数据结构定义，无外部依赖。
"""

from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class FailureRecord:
    """失败记录"""
    stock_code: str
    failure_count: int          # 失败次数
    last_failure_time: str      # 最后失败时间
    error_type: str             # 错误类型：'permanent'（永久）、'daily'（当日）或 'temporary'（临时）
    error_message: str          # 错误信息


@dataclass
class ZoneTradeParam:
    """单个区间的交易参数"""
    buy_dip_pct: float       # 买入跌幅百分比
    sell_rise_pct: float     # 卖出涨幅百分比
    stop_loss_pct: float     # 止损百分比


@dataclass
class CachedAnalysisParams:
    """缓存的回测分析参数（每只股票一份，当日有效）"""
    stock_code: str
    zone_params: Dict[str, ZoneTradeParam] = field(default_factory=dict)
    open_type_params: Dict[str, ZoneTradeParam] = field(default_factory=dict)
    gap_threshold: float = 0.5
    skip_gap_down: bool = False
    analyzed_at: str = ''
    expires_at: str = ''

    @staticmethod
    def from_analysis_result(
        stock_code: str,
        result: Dict,
        analyzed_at: str,
        expires_at: str,
    ) -> 'CachedAnalysisParams':
        """从 AnalysisService 的分析结果构建缓存参数"""
        # 解析 zone 参数
        zone_params: Dict[str, ZoneTradeParam] = {}
        raw_trade_params = result.get('trade_params', {})
        for zone_name, params in raw_trade_params.items():
            if params.get('buy_dip_pct', 0) > 0:
                zone_params[zone_name] = ZoneTradeParam(
                    buy_dip_pct=params['buy_dip_pct'],
                    sell_rise_pct=params['sell_rise_pct'],
                    stop_loss_pct=params['stop_loss_pct'],
                )

        # 解析开盘类型参数
        open_type_params: Dict[str, ZoneTradeParam] = {}
        raw_ot = result.get('open_type_params', {})
        for ot_key in ('gap_up', 'gap_down'):
            ot_data = raw_ot.get(ot_key, {})
            if ot_data.get('enabled', False) and ot_data.get('buy_dip_pct', 0) > 0:
                open_type_params[ot_key] = ZoneTradeParam(
                    buy_dip_pct=ot_data['buy_dip_pct'],
                    sell_rise_pct=ot_data['sell_rise_pct'],
                    stop_loss_pct=ot_data['stop_loss_pct'],
                )

        # 低开日是否跳过
        gap_down_data = raw_ot.get('gap_down', {})
        skip_gap_down = (
            not gap_down_data.get('enabled', False)
            or gap_down_data.get('recommendation') == 'skip'
        )

        return CachedAnalysisParams(
            stock_code=stock_code,
            zone_params=zone_params,
            open_type_params=open_type_params,
            gap_threshold=result.get('gap_threshold', 0.5),
            skip_gap_down=skip_gap_down,
            analyzed_at=analyzed_at,
            expires_at=expires_at,
        )


@dataclass
class LiveTradeTargets:
    """当日实时交易目标价（每只股票每天计算一次）"""
    stock_code: str
    zone: str
    open_type: str          # gap_up / flat / gap_down
    anchor_price: float
    prev_close: float
    open_price: float
    buy_target: float
    sell_target: float
    stop_price: float
    buy_dip_pct: float
    sell_rise_pct: float
    stop_loss_pct: float
    calculated_at: str = ''

    def to_dict(self) -> Dict:
        return {
            'stock_code': self.stock_code,
            'zone': self.zone,
            'open_type': self.open_type,
            'anchor_price': self.anchor_price,
            'prev_close': self.prev_close,
            'open_price': self.open_price,
            'buy_target': self.buy_target,
            'sell_target': self.sell_target,
            'stop_price': self.stop_price,
            'buy_dip_pct': self.buy_dip_pct,
            'sell_rise_pct': self.sell_rise_pct,
            'stop_loss_pct': self.stop_loss_pct,
            'calculated_at': self.calculated_at,
        }
