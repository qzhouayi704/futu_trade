#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
日内高频防砸盘与真空区止盈引擎 (Intraday Risk Manager)

基于量化盘口和资金流数据，在实盘持仓中执行：
1. 破位止损 (Breakdown Stop Loss)
2. 真空区半仓止盈 (Vacuum Zone Half-Sell)
3. 大单买入占比骤降 (Capital Flow Plunge)
"""

import logging
from typing import Dict, Any, Optional, List

from .lot_order_take_profit import LotOrderTakeProfitService
from ...analysis.intraday_levels_service import IntradayLevelsService

logger = logging.getLogger(__name__)


class IntradayRiskManager:
    """日内高频防砸盘与真空区止盈引擎"""

    def __init__(self, db_manager, futu_client, intraday_levels_service: IntradayLevelsService, futu_trade_service=None):
        self.db_manager = db_manager
        self.futu_client = futu_client
        self.levels_service = intraday_levels_service
        self.profit_taker = LotOrderTakeProfitService(db_manager, futu_trade_service)
        # 缓存上一分钟的资金流占比，用来计算突降: {stock_code: ratio}
        self._last_ratios: Dict[str, float] = {}

    async def check_risks(
        self, 
        stock_code: str, 
        quote: Dict[str, Any], 
        position_info: Dict[str, Any], 
        capital_flow: Optional[Dict[str, Any]] = None
    ) -> List[Dict]:
        """
        高频检查持仓风险并触发条件单
        :param position_info: 必须包含 cost_price, qty 等信息，代表当前有持仓
        :return: 触发的交易信号列表 (trade_actions)
        """
        actions = []
        if not position_info or position_info.get('qty', 0) <= 0:
            return actions

        current_price = quote.get('last_price', 0)
        if current_price <= 0:
            return actions

        cost_price = position_info.get('cost_price', 0)
        profit_pct = (current_price - cost_price) / cost_price * 100 if cost_price > 0 else 0
        qty = position_info['qty']

        try:
            # 获取日内关键价位
            levels_result = await self.levels_service.get_levels(stock_code)

            # 计算动态容忍度（基于近20日平均振幅）
            # 回测结论：K=4（容忍 1/4 平均振幅）在误杀率与捕获率之间取得平衡
            breakdown_tol = self._get_dynamic_tolerance(stock_code, k_divisor=4, default_pct=2.0)
            vacuum_tol = max(breakdown_tol * 1.5, 0.015)  # 真空区阈值 = 1.5倍破位容忍度，下限1.5%

            # ========== 1. 破位止损 (Breakdown Stop Loss) ==========
            strong_support = self.levels_service.get_nearest_strong_support(levels_result, current_price, min_strength=80)
            if strong_support:
                # 安全校验：仅信任真实成交验证的支撑位，挂单墙可被随时撤单(Spoofing)
                if getattr(strong_support, 'reliability', 'confirmed') == 'order_book_only':
                    logger.debug(f"[{stock_code}] 跳过挂单墙支撑 {strong_support.price}（不可信，可能是假墙）")
                    strong_support = None  # 降级：不使用未经成交验证的支撑位做止损
                elif current_price < strong_support.price * (1 - breakdown_tol):
                    # 资金流确认：主力净流入时跳过止损（可能是洗盘而非出货）
                    main_net = capital_flow.get('main_net_inflow', 0) if capital_flow else 0
                    if main_net > 0:
                        logger.info(
                            f"[{stock_code}] 跌破支撑 {strong_support.price} 但主力净流入 {main_net:.0f}万，"
                            f"疑似洗盘，暂不止损 (容忍度:{breakdown_tol*100:.1f}%)"
                        )
                    else:
                        logger.warning(
                            f"[{stock_code}] 触发破位止损！现价 {current_price} 跌破强支撑 "
                            f"{strong_support.price} (容忍度:{breakdown_tol*100:.1f}%, 标签:{strong_support.label})"
                        )
                        self._execute_sell(stock_code, qty, f"破位止损: 跌破 {strong_support.price}")
                        actions.append({
                            'stock_code': stock_code,
                            'stock_name': quote.get('name', stock_code),
                            'signal_type': 'SELL',
                            'price': current_price,
                            'reason': f"破位强支撑 {strong_support.price} (标签:{strong_support.label})",
                            'message': "触发自动止损",
                            'timestamp': quote.get('data_time', '')
                        })
                        return actions

            # ========== 2. 真空区半仓止盈 (Vacuum Zone Half-Sell) ==========
            # 必须是盈利状态，且大于 10%
            if profit_pct > 10.0:
                nearest_res = self.levels_service.get_nearest_strong_resistance(levels_result, current_price, min_strength=60)
                if strong_support and nearest_res:
                    dist_up = (nearest_res.price - current_price) / current_price
                    dist_down = (current_price - strong_support.price) / current_price
                    
                    # 动态真空区阈值（根据波动率缩放）
                    if dist_up > vacuum_tol and dist_down > vacuum_tol:
                        half_qty = int(qty / 2)
                        if half_qty > 0:
                            logger.info(
                                f"[{stock_code}] 触发真空区止盈！距离上下支撑/阻力均>{vacuum_tol*100:.1f}%，"
                                f"浮盈 {profit_pct:.1f}%"
                            )
                            self._execute_sell(stock_code, half_qty, f"真空区半仓止盈: 浮盈 {profit_pct:.1f}%")
                            actions.append({
                                'stock_code': stock_code,
                                'stock_name': quote.get('name', stock_code),
                                'signal_type': 'SELL',
                                'price': current_price,
                                'reason': f"真空区半仓止盈: 浮盈 {profit_pct:.1f}%",
                                'message': "触发自动半仓止盈",
                                'timestamp': quote.get('data_time', '')
                            })
                            return actions

            # ========== 3. 大单买入占比骤降 (Capital Flow Plunge) ==========
            if capital_flow and 'big_order_buy_ratio' in capital_flow:
                ratio = capital_flow['big_order_buy_ratio']
                last_ratio = self._last_ratios.get(stock_code)
                
                if last_ratio is not None:
                    # 如果 5 分钟内占比暴跌 > 5% (比如从 55% 跌到 49%) 且净流出
                    if (last_ratio - ratio) > 0.05 and ratio < 0.50 and capital_flow.get('main_net_inflow', 0) < 0:
                        logger.warning(f"[{stock_code}] 资金流预警！大单占比骤降至 {ratio*100:.1f}%，疑似出货")
                        self._execute_sell(stock_code, qty, f"大单骤降逃顶: {ratio*100:.1f}%")
                        actions.append({
                            'stock_code': stock_code,
                            'stock_name': quote.get('name', stock_code),
                            'signal_type': 'SELL',
                            'price': current_price,
                            'reason': f"大单占比骤降至 {ratio*100:.1f}%",
                            'message': "触发大单逃顶卖出",
                            'timestamp': quote.get('data_time', '')
                        })
                        return actions
                
                # 更新缓存，这里假设每次检查都是 1 分钟/5分钟级别的，可以引入时间衰减逻辑，为简化先直接覆盖
                self._last_ratios[stock_code] = ratio
                
        except Exception as e:
            logger.error(f"[{stock_code}] 日内风控检查发生异常: {e}")
        
        return actions

    def _get_dynamic_tolerance(self, stock_code: str, k_divisor: int = 4, default_pct: float = 2.0) -> float:
        """基于近20日平均振幅计算动态破位容忍度

        回测结论：K=4 时误杀率与捕获率取得最佳平衡。
        例如平均振幅 8.6% → 容忍度 8.6/4 = 2.15%

        Returns:
            容忍度比例（小数形式），如 0.02 表示 2%
        """
        try:
            rows = self.db_manager.execute_query("""
                SELECT high_price, low_price FROM kline_data
                WHERE stock_code = ? AND low_price > 0
                ORDER BY time_key DESC LIMIT 20
            """, (stock_code,))

            if rows and len(rows) >= 5:
                amplitudes = [(r[0] - r[1]) / r[1] * 100 for r in rows]
                avg_amp = sum(amplitudes) / len(amplitudes)
                tol = avg_amp / k_divisor / 100
                # 设定上下限：最小 0.5%，最大 5%（回测结论：>5%容忍度反而增加误杀）
                tol = max(0.005, min(tol, 0.05))
                return tol
        except Exception as e:
            logger.debug(f"[{stock_code}] 获取动态容忍度失败: {e}")

        return default_pct / 100  # 默认 2%

    def _execute_sell(self, stock_code: str, qty: float, reason: str) -> None:
        """调用实际接口执行市价卖出"""
        try:
            logger.info(f"[{stock_code}] 🚀 执行自动卖出: {qty}股, 原因: {reason}")
            # 调用底层接口执行卖出 (exec_id 用 0 代替系统自动触发)
            result = self.profit_taker.execute_market_sell(0, stock_code, qty)
            if result:
                logger.info(f"[{stock_code}] 卖出下单成功: {result}")
            else:
                logger.error(f"[{stock_code}] 卖出下单失败，请检查资金和网络")
        except Exception as e:
            logger.error(f"[{stock_code}] 执行自动卖出时发生崩溃: {e}")
