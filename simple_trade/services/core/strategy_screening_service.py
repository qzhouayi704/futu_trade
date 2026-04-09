#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
策略筛选服务（协调器）

职责：
- 协调筛选引擎和缓存管理器
- 提供统一的筛选接口
- 管理K线额度检查
- 对外提供API接口
"""

import logging
from datetime import datetime
from typing import Dict, List, Any, Optional, Set

from ...database.core.db_manager import DatabaseManager
from ...config.config import Config
from ...core.coordination.strategy_dispatcher import StrategyDispatcher
from ..strategy import ScreeningEngine, ScreeningCache, ScreeningResult


class StrategyScreeningService:
    """
    策略筛选服务（协调器）

    功能：
    1. 根据策略条件筛选股票池中的股票
    2. 生成筛选结果（买入信号、卖出信号）
    3. 结果显示在主页实时列表中
    4. K线额度不足时自动切换到已缓存数据模式

    注意：此服务不执行任何交易操作，只提供筛选和提示功能
    """

    def __init__(self, db_manager: DatabaseManager, config: Config,
                 stock_data_service=None, kline_service=None,
                 futu_trade_service=None, strategy_dispatcher: StrategyDispatcher = None):
        self.db_manager = db_manager
        self.config = config
        self.stock_data_service = stock_data_service
        self.kline_service = kline_service  # K线服务，用于检查额度
        self.futu_trade_service = futu_trade_service  # 交易服务，用于获取实际持仓

        # 创建子服务（使用 StrategyDispatcher 替代硬编码的 SwingStrategy）
        self.strategy_dispatcher = strategy_dispatcher
        self.engine = ScreeningEngine(db_manager, strategy_dispatcher)
        self.cache = ScreeningCache(db_manager, config, futu_trade_service)

        # 筛选模式状态
        self._screening_mode: str = 'normal'  # 'normal' 或 'cached_only'
        self._quota_insufficient: bool = False  # K线额度是否不足

        logging.info("策略筛选服务初始化完成")

    def set_kline_service(self, kline_service):
        """设置K线服务（用于后期注入）"""
        self.kline_service = kline_service
        logging.info("K线服务已注入到策略筛选服务")

    def _check_kline_quota(self) -> Dict[str, Any]:
        """检查K线额度

        Returns:
            额度信息字典，包含：
            - has_quota: 是否有足够额度
            - remaining: 剩余额度
            - message: 状态消息
        """
        result = {
            'has_quota': True,
            'remaining': -1,  # -1 表示未知
            'message': '额度检查未执行'
        }

        try:
            if not self.kline_service:
                result['message'] = 'K线服务未配置，使用默认模式'
                return result

            # 获取K线额度信息
            quota_info = self.kline_service.get_quota_info()

            if quota_info['status'] != 'connected':
                result['has_quota'] = False
                result['message'] = f"K线API状态异常: {quota_info['status']}"
                return result

            remaining = quota_info.get('remaining', 0)
            result['remaining'] = remaining

            # 设置额度阈值（低于此值时切换到缓存模式）
            quota_threshold = getattr(self.config, 'kline_quota_threshold', 10)

            if remaining <= quota_threshold:
                result['has_quota'] = False
                result['message'] = f"K线额度不足: 剩余{remaining}，阈值{quota_threshold}"
                logging.warning(result['message'])
            else:
                result['message'] = f"K线额度充足: 剩余{remaining}"

        except Exception as e:
            logging.error(f"检查K线额度失败: {e}")
            result['message'] = f"额度检查异常: {str(e)}"

        return result

    def _filter_quotes_by_kline_availability(
        self,
        quotes: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """根据K线数据可用性筛选报价

        当K线额度不足时，只返回已有K线数据的股票

        Args:
            quotes: 原始报价列表

        Returns:
            筛选后的报价列表
        """
        required_days = self.strategy_dispatcher.get_max_required_kline_days()
        stocks_with_kline = self.cache.get_stocks_with_kline_data(required_days)

        if not stocks_with_kline:
            logging.warning("没有找到有K线数据的股票，将使用全部报价")
            return quotes

        filtered = [q for q in quotes if q.get('code', '') in stocks_with_kline]

        skipped_count = len(quotes) - len(filtered)
        if skipped_count > 0:
            logging.info(f"K线额度不足模式: 筛选{len(filtered)}只有K线数据的股票，跳过{skipped_count}只")

        return filtered

    def screen_stocks(self, quotes: List[Dict[str, Any]],
                     check_kline_quota: bool = True) -> List[ScreeningResult]:
        """
        筛选股票

        支持K线额度不足时自动切换到已缓存数据模式：
        - 当K线额度充足时，对所有报价股票进行策略筛选
        - 当K线额度不足时，只对已有K线数据的股票进行筛选

        Args:
            quotes: 实时报价数据列表
            check_kline_quota: 是否检查K线额度（默认True）

        Returns:
            筛选结果列表（只返回有信号的股票）
        """
        results = []
        all_results = {}

        # 获取所有持仓信息（包含成本价）
        positions_dict = {}
        if self.futu_trade_service:
            try:
                positions_result = self.futu_trade_service.get_positions()
                if positions_result['success']:
                    positions_dict = {
                        pos['stock_code']: pos
                        for pos in positions_result['positions']
                        if pos.get('qty', 0) > 0
                    }
                    logging.debug(f"获取到 {len(positions_dict)} 只持仓信息（含成本价）")
            except Exception as e:
                logging.warning(f"获取持仓信息失败，止损检查将使用降级方案: {e}")

        # 检查K线额度并决定筛选模式
        if check_kline_quota:
            quota_result = self._check_kline_quota()

            if not quota_result['has_quota']:
                # K线额度不足，切换到缓存模式
                self._quota_insufficient = True
                self._screening_mode = 'cached_only'

                # 筛选出有K线数据的股票
                original_count = len(quotes)
                quotes = self._filter_quotes_by_kline_availability(quotes)

                logging.debug(f"K线额度不足模式: 从{original_count}只股票中筛选出{len(quotes)}只有K线数据的股票进行策略判断")
            else:
                # 额度充足，使用正常模式
                self._quota_insufficient = False
                self._screening_mode = 'normal'

        for quote in quotes:
            try:
                stock_code = quote.get('code', '')
                if not stock_code:
                    continue

                # 获取持仓信息
                position_info = positions_dict.get(stock_code)

                # 使用引擎筛选单只股票
                result = self.engine.screen_single_stock(quote, position_info)

                all_results[stock_code] = result

                # 只有有信号的才加入返回列表
                if result.signal_type != 'NONE':
                    results.append(result)
                    logging.info(f"筛选信号: {result.signal_type} {stock_code} - {result.signal_reason}")

            except Exception as e:
                logging.error(f"筛选股票 {quote.get('code', 'unknown')} 失败: {e}")

        # 更新缓存
        self.cache.update_screening_results(all_results)

        logging.debug(f"筛选完成: {len(quotes)}只股票, {len(results)}个信号")

        return results

    def get_screening_summary(self) -> Dict[str, Any]:
        """获取筛选摘要"""
        all_results = self.cache.get_screening_results()
        buy_signals = [r for r in all_results.values() if r.signal_type == 'BUY']
        sell_signals = [r for r in all_results.values() if r.signal_type == 'SELL']
        last_time = self.cache.get_last_screening_time()

        kline_info = self.cache.get_kline_cache_info()

        return {
            'total_stocks': len(all_results),
            'buy_signals': len(buy_signals),
            'sell_signals': len(sell_signals),
            'last_screening_time': last_time.isoformat() if last_time else None,
            'buy_signal_stocks': [r.to_dict() for r in buy_signals],
            'sell_signal_stocks': [r.to_dict() for r in sell_signals],
            # 添加筛选模式信息
            'screening_mode': self._screening_mode,
            'quota_insufficient': self._quota_insufficient,
            'stocks_with_kline_count': kline_info['stocks_with_kline']
        }

    def get_screening_mode_info(self) -> Dict[str, Any]:
        """获取当前筛选模式信息

        Returns:
            筛选模式信息，包含：
            - mode: 当前模式 ('normal' 或 'cached_only')
            - quota_insufficient: K线额度是否不足
            - stocks_with_kline: 有K线数据的股票数量
            - message: 状态描述
        """
        kline_info = self.cache.get_kline_cache_info()
        stocks_with_kline = kline_info['stocks_with_kline']

        if self._screening_mode == 'cached_only':
            message = f"K线额度不足模式: 仅使用{stocks_with_kline}只已有K线数据的股票"
        else:
            message = "正常模式: 对所有订阅股票进行策略筛选"

        return {
            'mode': self._screening_mode,
            'quota_insufficient': self._quota_insufficient,
            'stocks_with_kline': stocks_with_kline,
            'kline_cache_valid': kline_info['kline_cache_valid'],
            'message': message
        }

    def refresh_kline_cache(self) -> int:
        """强制刷新K线数据缓存

        Returns:
            有K线数据的股票数量
        """
        required_days = self.strategy_dispatcher.get_max_required_kline_days()
        return self.cache.refresh_kline_cache(required_days)

    def get_stock_screening_result(self, stock_code: str) -> Optional[ScreeningResult]:
        """获取单只股票的筛选结果"""
        return self.cache.get_stock_result(stock_code)

    def get_all_screening_results(self) -> List[Dict[str, Any]]:
        """获取所有筛选结果（用于交易条件页面显示）"""
        all_results = self.cache.get_screening_results()
        return [r.to_dict() for r in all_results.values()]

    def format_for_homepage(self, results: List[ScreeningResult],
                           filter_hot_only: bool = True) -> List[Dict[str, Any]]:
        """
        格式化筛选结果用于主页显示

        【重要】只显示热门股票(Top 100)和持仓股票的信号

        Args:
            results: 筛选结果列表
            filter_hot_only: 是否只显示热门股票的信号（默认True）

        Returns:
            适合主页conditions区域显示的数据格式
        """
        formatted = []

        # 如果开启热门过滤，获取热门股票集合
        if filter_hot_only:
            hot_codes = self.cache.get_hot_stock_codes()
            position_codes = self.cache.get_position_codes()
            allowed_codes = hot_codes | position_codes  # 热门 + 持仓

            if allowed_codes:
                logging.debug(f"首页信号过滤: 允许显示 {len(hot_codes)} 只热门股票 + {len(position_codes)} 只持仓股票的信号")
        else:
            allowed_codes = None

        for result in results:
            # 如果开启过滤，检查是否在允许列表中
            if allowed_codes is not None and result.stock_code not in allowed_codes:
                logging.debug(f"过滤非热门股票信号: {result.stock_code} ({result.stock_name})")
                continue

            formatted.append({
                'stock_code': result.stock_code,
                'stock_name': result.stock_name,
                'signal_type': result.signal_type,
                'condition_text': f"{result.signal_type}信号: {result.signal_reason}",
                'timestamp': result.timestamp,
                'price': result.strategy_data.get('today_low', 0) if result.signal_type == 'BUY' else result.strategy_data.get('today_high', 0),
                'reason': result.signal_reason,
                'plate_name': result.plate_name,
                'strategy_name': result.strategy_name
            })

        return formatted

    def is_hot_stock(self, stock_code: str) -> bool:
        """判断股票是否是热门股票（或持仓股票）

        Args:
            stock_code: 股票代码

        Returns:
            True 如果是热门股票或持仓股票
        """
        return self.cache.is_hot_stock(stock_code)

    def get_hot_stock_filter_info(self) -> Dict[str, Any]:
        """获取热门股票过滤信息

        Returns:
            过滤器状态信息
        """
        return self.cache.get_hot_stock_filter_info()
