#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
激进策略信号处理器

负责信号的筛选、评分、排序和验证
"""

import logging
from datetime import datetime
from typing import List, Dict, Any, Optional
from ....database.core.db_manager import DatabaseManager
from ....core.validation.signal_scorer import SignalScorer, SignalScore
from ...market_data.plate.plate_strength_service import PlateStrengthService, PlateStrengthScore
from ...market_data.leader_stock_filter import LeaderStockFilter


class AggressiveSignalProcessor:
    """
    激进策略信号处理器

    职责：
    1. 从强势板块中筛选龙头股
    2. 对候选股票进行评分
    3. 按评分排序和筛选
    4. 计算资金分配
    5. 生成信号原因描述
    """

    def __init__(
        self,
        db_manager: DatabaseManager,
        signal_scorer: SignalScorer,
        leader_filter: LeaderStockFilter,
        plate_strength_service: PlateStrengthService,
        realtime_service,
        kline_service
    ):
        """
        初始化信号处理器

        Args:
            db_manager: 数据库管理器
            signal_scorer: 信号评分器
            leader_filter: 龙头股筛选器
            plate_strength_service: 板块强势度服务
            realtime_service: 实时行情服务
            kline_service: K线数据服务
        """
        self.db_manager = db_manager
        self.signal_scorer = signal_scorer
        self.leader_filter = leader_filter
        self.plate_strength_service = plate_strength_service
        self.realtime_service = realtime_service
        self.kline_service = kline_service
        self.logger = logging.getLogger(__name__)

    async def filter_leader_stocks(
        self,
        strong_plates: List[PlateStrengthScore]
    ) -> List[Dict[str, Any]]:
        """
        从强势板块中筛选龙头股

        Args:
            strong_plates: 强势板块列表

        Returns:
            龙头股候选列表，包含股票信息和板块信息
        """
        try:
            all_candidates = []

            for plate_score in strong_plates:
                # 获取板块内股票
                stocks = self.db_manager.stock_queries.get_stocks_by_plate(plate_score.plate_code)
                if not stocks:
                    continue

                stock_codes = [s['code'] for s in stocks]

                # 获取实时行情
                quotes_result = self.realtime_service.get_realtime_quotes(stock_codes)
                if not quotes_result or not quotes_result.get('success'):
                    continue
                # 将 quotes 列表转换为字典格式
                quotes = {}
                for q in quotes_result.get('quotes', []):
                    if q and isinstance(q, dict) and 'code' in q:
                        quotes[q['code']] = q
                if not quotes:
                    continue

                # 获取K线数据（用于计算价格位置）
                kline_data_map = {}
                for stock_code in stock_codes:
                    klines = self.kline_service.get_kline_data(stock_code, days=30)
                    if klines:
                        kline_data_map[stock_code] = klines

                # 筛选龙头股
                leaders = self.leader_filter.filter_leaders(
                    quotes=quotes,
                    kline_data_map=kline_data_map
                )

                # 添加板块信息
                for leader in leaders:
                    all_candidates.append({
                        'stock_code': leader.stock_code,
                        'stock_name': leader.stock_name,
                        'change_pct': leader.change_pct,
                        'volume': leader.volume,
                        'price': leader.current_price,
                        'price_position': leader.price_position,
                        'plate_code': plate_score.plate_code,
                        'plate_name': plate_score.plate_name,
                        'plate_strength': plate_score.strength_score,
                        'plate_rank': strong_plates.index(plate_score) + 1
                    })

            return all_candidates

        except Exception as e:
            self.logger.error(f"筛选龙头股失败: {e}", exc_info=True)
            return []

    async def score_and_filter_signals(
        self,
        candidates: List[Dict[str, Any]],
        strong_plates: List[PlateStrengthScore]
    ) -> List[Dict[str, Any]]:
        """
        对候选股票进行评分和筛选

        Args:
            candidates: 龙头股候选列表
            strong_plates: 强势板块列表

        Returns:
            筛选后的信号列表（最多max_daily_signals个）
        """
        try:
            # 获取当前持仓股票
            held_positions = self.db_manager.stock_queries.get_active_positions()
            held_stock_codes = set(pos['stock_code'] for pos in held_positions)

            if held_stock_codes:
                self.logger.info(f"当前持仓股票: {held_stock_codes}")

            # 排除已持仓股票
            candidates = [c for c in candidates if c['stock_code'] not in held_stock_codes]
            self.logger.info(f"排除持仓后剩余候选股票: {len(candidates)}只")

            # 对每个候选股票进行评分
            scored_signals = []
            for candidate in candidates:
                # 计算信号评分
                signal_score = self.signal_scorer.score_signal(
                    stock_code=candidate['stock_code'],
                    plate_strength=candidate['plate_strength'],
                    plate_rank=candidate['plate_rank'],
                    change_pct=candidate['change_pct'],
                    volume=candidate['volume'],
                    price_position=candidate['price_position']
                )

                if signal_score.total_score >= self.signal_scorer.min_score:
                    scored_signals.append({
                        'stock_code': candidate['stock_code'],
                        'stock_name': candidate['stock_name'],
                        'signal_type': 'buy',
                        'price': candidate['price'],
                        'plate_name': candidate['plate_name'],
                        'plate_strength': candidate['plate_strength'],
                        'signal_score': signal_score.total_score,
                        'reason': self._generate_signal_reason(candidate, signal_score),
                        'created_at': datetime.now().isoformat()
                    })

            # 按评分排序，取前N个
            max_signals = self.signal_scorer.max_daily_signals
            scored_signals.sort(key=lambda x: x['signal_score'], reverse=True)
            top_signals = scored_signals[:max_signals]

            # 计算资金分配（按评分加权）
            if top_signals:
                top_signals = self._calculate_position_sizes(top_signals)

            return top_signals

        except Exception as e:
            self.logger.error(f"评分和筛选信号失败: {e}", exc_info=True)
            return []

    def _calculate_position_sizes(self, signals: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        按信号评分加权计算资金分配

        Args:
            signals: 信号列表，每项包含 signal_score 字段

        Returns:
            添加了 position_weight 和 position_percentage 字段的信号列表
        """
        try:
            if not signals:
                return signals

            # 计算总评分
            total_score = sum(s['signal_score'] for s in signals)

            if total_score == 0:
                # 如果总评分为0，平均分配
                equal_weight = 1.0 / len(signals)
                for signal in signals:
                    signal['position_weight'] = equal_weight
                    signal['position_percentage'] = round(equal_weight * 100, 2)
                self.logger.warning("信号总评分为0，使用平均分配")
            else:
                # 按评分比例分配权重
                for signal in signals:
                    signal['position_weight'] = signal['signal_score'] / total_score
                    signal['position_percentage'] = round(signal['position_weight'] * 100, 2)

            # 记录资金分配结果
            allocation_info = [
                f"{s['stock_code']}({s['signal_score']:.1f}分): {s['position_percentage']:.2f}%"
                for s in signals
            ]
            self.logger.info(f"资金分配: {', '.join(allocation_info)}")

            return signals

        except Exception as e:
            self.logger.error(f"计算资金分配失败: {e}", exc_info=True)
            return signals

    def _generate_signal_reason(
        self,
        candidate: Dict[str, Any],
        signal_score: SignalScore
    ) -> str:
        """
        生成信号原因描述

        Args:
            candidate: 候选股票信息
            signal_score: 信号评分

        Returns:
            信号原因描述字符串
        """
        reasons = []
        reasons.append(f"板块【{candidate['plate_name']}】强势度{candidate['plate_strength']:.1f}分")
        reasons.append(f"涨幅{candidate['change_pct']:.2f}%")
        reasons.append(f"价格位置{candidate['price_position']:.1f}%")
        reasons.append(f"成交量{candidate['volume']/10000:.0f}万")
        reasons.append(f"信号评分{signal_score.total_score:.1f}分")
        return "；".join(reasons)
