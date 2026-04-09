#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
激进策略订单管理器

负责订单的保存、风险检查和止盈止损
"""

import logging
from datetime import datetime
from typing import List, Dict, Any, Optional
from ....database.core.db_manager import DatabaseManager
from ....core.validation.risk_checker import RiskChecker, RiskCheckResult
from ...market_data.plate.plate_strength_service import PlateStrengthService


class AggressiveOrderManager:
    """
    激进策略订单管理器

    职责：
    1. 保存交易信号到数据库
    2. 检查持仓风险（止盈止损）
    3. 获取板块排名
    4. 生成风险检查结果
    """

    def __init__(
        self,
        db_manager: DatabaseManager,
        risk_checker: RiskChecker,
        plate_strength_service: PlateStrengthService,
        plate_manager,
        realtime_service
    ):
        """
        初始化订单管理器

        Args:
            db_manager: 数据库管理器
            risk_checker: 风险检查器
            plate_strength_service: 板块强势度服务
            plate_manager: 板块管理服务
            realtime_service: 实时行情服务
        """
        self.db_manager = db_manager
        self.risk_checker = risk_checker
        self.plate_strength_service = plate_strength_service
        self.plate_manager = plate_manager
        self.realtime_service = realtime_service
        self.logger = logging.getLogger(__name__)

    def save_signal_to_db(self, signal: Dict[str, Any]) -> bool:
        """
        保存信号到数据库

        Args:
            signal: 信号字典，包含 stock_code, signal_type, price, reason 等字段

        Returns:
            是否保存成功
        """
        try:
            # 获取股票ID
            stock = self.db_manager.get_stock_by_code(signal['stock_code'])
            if not stock:
                self.logger.warning(f"未找到股票: {signal['stock_code']}")
                return False

            # 保存信号
            self.db_manager.add_trade_signal(
                stock_id=stock['id'],
                signal_type=signal['signal_type'],
                signal_price=signal['price'],
                condition_text=signal['reason']
            )

            self.logger.info(
                f"保存信号: {signal['stock_code']} "
                f"{signal['signal_type']} @ {signal['price']}"
            )
            return True

        except Exception as e:
            self.logger.error(f"保存信号失败: {e}", exc_info=True)
            return False

    def save_signals_batch(self, signals: List[Dict[str, Any]]) -> int:
        """
        批量保存信号到数据库

        Args:
            signals: 信号列表

        Returns:
            成功保存的信号数量
        """
        success_count = 0
        for signal in signals:
            if self.save_signal_to_db(signal):
                success_count += 1

        self.logger.info(f"批量保存信号: 成功 {success_count}/{len(signals)}")
        return success_count

    async def check_positions_risk(self) -> List[Dict[str, Any]]:
        """
        检查持仓风险（止盈止损）

        Returns:
            风险检查结果列表，每项包含：
            - stock_code: 股票代码
            - stock_name: 股票名称
            - action: 操作建议（SELL_PROFIT/SELL_LOSS）
            - reason: 原因
            - entry_price: 入场价格
            - current_price: 当前价格
            - profit_pct: 盈亏百分比
        """
        try:
            self.logger.info("开始检查持仓风险")

            # 获取当前持仓
            positions = self.db_manager.stock_queries.get_active_positions()
            if not positions:
                self.logger.info("无持仓需要检查")
                return []

            risk_results = []

            for position in positions:
                # 获取当前价格
                quotes_result = self.realtime_service.get_realtime_quotes([position['stock_code']])
                if not quotes_result or not quotes_result.get('success') or not quotes_result.get('quotes'):
                    continue
                quote = quotes_result['quotes'][0]
                current_price = quote.get('last_price', 0)
                if current_price <= 0:
                    continue

                # 获取板块排名
                plate_rank = self._get_plate_rank(position['stock_code'])

                # 检查风险
                risk_result = self.risk_checker.check_risk(
                    stock_code=position['stock_code'],
                    entry_price=position['entry_price'],
                    current_price=current_price,
                    entry_date=position['entry_date'],
                    plate_rank=plate_rank
                )

                if risk_result.action != 'HOLD':
                    risk_results.append({
                        'stock_code': position['stock_code'],
                        'stock_name': position['stock_name'],
                        'action': risk_result.action,
                        'reason': risk_result.reason,
                        'entry_price': position['entry_price'],
                        'current_price': current_price,
                        'profit_pct': risk_result.profit_pct
                    })

                    self.logger.info(
                        f"风险检查: {position['stock_code']} "
                        f"{risk_result.action} - {risk_result.reason}"
                    )

            return risk_results

        except Exception as e:
            self.logger.error(f"检查持仓风险失败: {e}", exc_info=True)
            return []

    def _get_plate_rank(self, stock_code: str) -> int:
        """
        获取股票所属板块的当前排名

        Args:
            stock_code: 股票代码

        Returns:
            板块排名（1-based），如果无法获取则返回999
        """
        try:
            # 获取股票所属板块
            plates = self.db_manager.stock_queries.get_plates_by_stock(stock_code)
            if not plates:
                return 999

            # 计算所有板块强势度并排名
            all_plates = self.plate_manager.get_all_plates()
            plate_scores = []

            for plate in all_plates:
                stocks = self.db_manager.stock_queries.get_stocks_by_plate(plate['code'])
                if not stocks:
                    continue

                stock_codes = [s['code'] for s in stocks]
                quotes_result = self.realtime_service.get_realtime_quotes(stock_codes)
                if not quotes_result or not quotes_result.get('success'):
                    continue
                # 将 quotes 列表转换为字典格式 {stock_code: quote_data}
                quotes = {}
                for q in quotes_result.get('quotes', []):
                    if q and isinstance(q, dict) and 'code' in q:
                        quotes[q['code']] = q
                if not quotes:
                    continue

                score = self.plate_strength_service.calculate_plate_strength(
                    plate_code=plate['code'],
                    plate_name=plate['name'],
                    market=plate.get('market', 'HK'),
                    quotes=quotes
                )

                if score:
                    plate_scores.append((plate['code'], score.strength_score))

            # 排序
            plate_scores.sort(key=lambda x: x[1], reverse=True)

            # 查找股票板块的排名
            for rank, (plate_code, _) in enumerate(plate_scores, 1):
                if plate_code in [p['code'] for p in plates]:
                    return rank

            return 999

        except Exception as e:
            self.logger.error(f"获取板块排名失败: {e}", exc_info=True)
            return 999

    def get_position_summary(self) -> Dict[str, Any]:
        """
        获取持仓汇总信息

        Returns:
            持仓汇总字典，包含：
            - total_positions: 总持仓数
            - total_value: 总市值
            - total_profit: 总盈亏
            - positions: 持仓列表
        """
        try:
            positions = self.db_manager.stock_queries.get_active_positions()
            if not positions:
                return {
                    'total_positions': 0,
                    'total_value': 0,
                    'total_profit': 0,
                    'positions': []
                }

            total_value = 0
            total_profit = 0
            position_details = []

            for position in positions:
                quotes_result = self.realtime_service.get_realtime_quotes([position['stock_code']])
                if not quotes_result or not quotes_result.get('success') or not quotes_result.get('quotes'):
                    continue
                quote = quotes_result['quotes'][0]
                current_price = quote.get('last_price', 0)
                if current_price <= 0:
                    continue

                quantity = position.get('quantity', 0)
                entry_price = position.get('entry_price', 0)

                position_value = current_price * quantity
                position_profit = (current_price - entry_price) * quantity
                profit_pct = ((current_price - entry_price) / entry_price * 100) if entry_price > 0 else 0

                total_value += position_value
                total_profit += position_profit

                position_details.append({
                    'stock_code': position['stock_code'],
                    'stock_name': position['stock_name'],
                    'quantity': quantity,
                    'entry_price': entry_price,
                    'current_price': current_price,
                    'position_value': position_value,
                    'position_profit': position_profit,
                    'profit_pct': profit_pct
                })

            return {
                'total_positions': len(positions),
                'total_value': total_value,
                'total_profit': total_profit,
                'positions': position_details
            }

        except Exception as e:
            self.logger.error(f"获取持仓汇总失败: {e}", exc_info=True)
            return {
                'total_positions': 0,
                'total_value': 0,
                'total_profit': 0,
                'positions': []
            }
