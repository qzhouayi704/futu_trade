#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
股票热度分数计算器

基础模式：量比、换手率、涨跌幅
增强模式：多维度热度（基础+资金流向+价格动能+板块联动）
"""

import logging
import time
from typing import Dict, Any, List, Optional
from ....api.futu_client import FutuClient
from ....api.market_types import ReturnCode
from ....utils.rate_limiter import wait_for_api
from ....utils.retry_helper import parse_error_type, ErrorType


class StockHeatCalculator:
    """股票热度分数计算器：基础模式（量比+换手率+涨跌幅）和增强模式（多维度），支持缓存"""

    # 归一化参数
    VOLUME_RATIO_THRESHOLD = 5.0  # 量比阈值
    TURNOVER_RATE_THRESHOLD = 10.0  # 换手率阈值（%）
    CHANGE_RATE_THRESHOLD = 10.0  # 涨跌幅阈值（%）

    # 权重配置
    WEIGHT_VOLUME_RATIO = 0.4  # 量比权重
    WEIGHT_TURNOVER_RATE = 0.3  # 换手率权重
    WEIGHT_CHANGE_RATE = 0.3  # 涨跌幅权重

    def __init__(self, futu_client: FutuClient = None, db_manager=None,
                 config: dict = None, *, ctx=None):
        """初始化热度计算器

        Args:
            ctx: AnalysisContext（推荐）
            futu_client: 富途API客户端（向后兼容）
            db_manager: 数据库管理器（向后兼容）
            config: 配置字典（向后兼容）
        """
        if ctx is not None:
            self.futu_client = ctx.futu_client
            self.db_manager = ctx.db_manager
            self.config = ctx.config
        else:
            self.futu_client = futu_client
            self.db_manager = db_manager
            self.config = config or {}
        self.logger = logging.getLogger(__name__)
        self._cache = {}  # 内存缓存

        # 检查是否启用增强模式
        enhanced_config = self.config.get('enhanced_heat_config', {})
        self.enhanced_enabled = enhanced_config.get('enabled', False)

        # 初始化增强模块（如果启用）
        if self.enhanced_enabled and self.db_manager:
            try:
                from .capital_flow_analyzer import CapitalFlowAnalyzer
                from .big_order_tracker import BigOrderTracker
                from .enhanced_heat_calculator import EnhancedHeatCalculator

                self.capital_analyzer = CapitalFlowAnalyzer(
                    self.futu_client, self.db_manager, self.config
                )
                self.big_order_tracker = BigOrderTracker(
                    self.futu_client, self.db_manager, self.config
                )
                self.enhanced_calculator = EnhancedHeatCalculator(
                    self.futu_client, self.db_manager,
                    self.capital_analyzer,
                    self.big_order_tracker,
                    self.config
                )
                self.logger.info("增强热度计算模式已启用")
            except Exception as e:
                self.logger.error(f"初始化增强模块失败: {e}")
                self.enhanced_enabled = False
        else:
            self.enhanced_calculator = None
            self.capital_analyzer = None
            self.big_order_tracker = None

        # 初始化无效股票检测器
        from ...market_data.invalid_stock_detector import InvalidStockDetector
        self.invalid_stock_detector = InvalidStockDetector(
            self.futu_client, self.db_manager
        )

    def _normalize_volume_ratio(self, volume_ratio: float) -> float:
        """量比归一化：量比 / 5.0，上限 1.0"""
        if volume_ratio is None or volume_ratio <= 0:
            return 0.0
        return min(volume_ratio / self.VOLUME_RATIO_THRESHOLD, 1.0)

    def _normalize_turnover_rate(self, turnover_rate: float) -> float:
        """换手率归一化：换手率 / 10.0，上限 1.0"""
        if turnover_rate is None or turnover_rate <= 0:
            return 0.0
        return min(turnover_rate / self.TURNOVER_RATE_THRESHOLD, 1.0)

    def _normalize_change_rate(self, change_rate: float) -> float:
        """涨跌幅归一化：|涨跌幅| / 10.0，上限 1.0"""
        if change_rate is None:
            return 0.0
        return min(abs(change_rate) / self.CHANGE_RATE_THRESHOLD, 1.0)

    def calculate_heat_score(
        self, volume_ratio: float, turnover_rate: float, change_rate: float
    ) -> float:
        """计算实时热度分 = (量比×0.4) + (换手率×0.3) + (涨跌幅×0.3)，返回 0-100"""
        score = (
            self._normalize_volume_ratio(volume_ratio) * self.WEIGHT_VOLUME_RATIO +
            self._normalize_turnover_rate(turnover_rate) * self.WEIGHT_TURNOVER_RATE +
            self._normalize_change_rate(change_rate) * self.WEIGHT_CHANGE_RATE
        )
        return round(score * 100, 2)  # 转换为 0-100 分制

    def calculate_realtime_heat_scores(
        self, stock_codes: List[str],
        use_cache: bool = True, cache_duration: int = 3600
    ) -> Dict[str, Dict[str, Any]]:
        """计算实时热度分（使用 get_market_snapshot API，带缓存和无效股票容错）"""
        heat_scores = {}

        if not stock_codes:
            self.logger.warning("股票代码列表为空")
            return heat_scores

        # 检查缓存
        if use_cache:
            cache_key = f"realtime_heat_{int(time.time() / cache_duration)}"
            cached_data = self._get_cache(cache_key)
            if cached_data:
                filtered = {c: cached_data[c] for c in stock_codes if c in cached_data}
                self.logger.info(f"从缓存返回 {len(filtered)}/{len(stock_codes)} 只股票热度数据")
                return filtered

        try:
            self.logger.info(f"开始计算 {len(stock_codes)} 只股票的实时热度")

            batch_size = 400
            for i in range(0, len(stock_codes), batch_size):
                batch = stock_codes[i:i + batch_size]
                batch_num = i // batch_size + 1

                # 使用带容错的批量获取（自动检测并剔除无效股票）
                data = self._fetch_batch_with_retry(batch, batch_num)

                if data is None or data.empty:
                    self.logger.warning(f"批次 {batch_num} 无有效数据，跳过")
                    continue

                # 解析并计算热度分
                for _, row in data.iterrows():
                    code = row.get('code', '')
                    if not code:
                        continue

                    volume_ratio = float(row.get('volume_ratio', 0) or 0)
                    turnover_rate = float(row.get('turnover_rate', 0) or 0)
                    last_price = float(row.get('last_price', 0) or 0)
                    prev_close = float(row.get('prev_close_price', 0) or 0)
                    change_rate = ((last_price - prev_close) / prev_close * 100
                                   if prev_close > 0 else 0.0)

                    heat_scores[code] = {
                        'heat_score': self.calculate_heat_score(
                            volume_ratio, turnover_rate, change_rate
                        ),
                        'volume_ratio': round(volume_ratio, 2),
                        'turnover_rate': round(turnover_rate, 2),
                        'change_rate': round(change_rate, 2)
                    }

                # 批次间通过频率限制器控制，无需额外固定延迟

            self.logger.info(f"热度计算完成: {len(heat_scores)}/{len(stock_codes)} 只股票")

            if use_cache and heat_scores:
                cache_key = f"realtime_heat_{int(time.time() / cache_duration)}"
                self._set_cache(cache_key, heat_scores, cache_duration)

        except Exception as e:
            self.logger.error(f"计算实时热度失败: {e}", exc_info=True)

        return heat_scores


    def _fetch_batch_with_retry(self, batch: List[str], batch_num: int) -> Optional[Any]:
        """带容错的批量获取市场快照

        流程：
        1. 频率限制等待 → 尝试批量获取
        2. 如果频率限制错误 → 等待后重试（最多2次）
        3. 如果无效股票错误 → 检测并剔除无效股票 → 重试
        4. 其他错误 → 返回 None
        """
        max_rate_limit_retries = 2

        for attempt in range(1 + max_rate_limit_retries):
            # 每次调用前等待频率限制
            wait_for_api('market_snapshot')

            try:
                ret, data = self.futu_client.client.get_market_snapshot(batch)

                if ReturnCode.is_ok(ret):
                    return data

                error_msg = data if isinstance(data, str) else str(data)
                error_type = parse_error_type(error_msg)

                # 频率限制错误：等待后重试
                if error_type == ErrorType.RATE_LIMIT:
                    if attempt < max_rate_limit_retries:
                        wait_seconds = 30 * (attempt + 1)
                        self.logger.warning(
                            f"批次 {batch_num} 触发频率限制，等待 {wait_seconds} 秒后重试 "
                            f"({attempt + 1}/{max_rate_limit_retries})"
                        )
                        time.sleep(wait_seconds)
                        continue
                    else:
                        self.logger.warning(f"批次 {batch_num} 频率限制重试已耗尽，跳过")
                        return None

                self.logger.warning(f"批次 {batch_num} 获取市场快照失败: {error_msg}")

                # 非无效股票错误，直接返回 None
                if not self.invalid_stock_detector.is_invalid_stock_error(error_msg):
                    return None

            except Exception as e:
                self.logger.error(f"批次 {batch_num} 获取快照异常: {e}", exc_info=True)
                return None

            # 以下处理无效股票错误（只在第一次尝试时执行）
            break

        # 检测并剔除无效股票
        try:
            self.logger.info(f"批次 {batch_num} 疑似包含无效股票，开始检测...")
            invalid_stocks, valid_stocks = self.invalid_stock_detector.detect_invalid_stocks(batch)

            if invalid_stocks:
                self.logger.warning(
                    f"批次 {batch_num} 检测到 {len(invalid_stocks)} 只无效股票: "
                    f"{', '.join(invalid_stocks[:5])}"
                    f"{'...' if len(invalid_stocks) > 5 else ''}"
                )
                # 从数据库移除无效股票
                self.invalid_stock_detector.remove_invalid_stocks(invalid_stocks)

            if not valid_stocks:
                self.logger.warning(f"批次 {batch_num} 剔除无效股票后无剩余有效股票")
                return None

        except Exception as e:
            self.logger.error(f"批次 {batch_num} 无效股票检测异常: {e}", exc_info=True)
            return None

        # 第二次尝试：用有效股票重试
        try:
            wait_for_api('market_snapshot')
            self.logger.info(f"批次 {batch_num} 使用 {len(valid_stocks)} 只有效股票重试")
            ret, data = self.futu_client.client.get_market_snapshot(valid_stocks)

            if ReturnCode.is_ok(ret):
                return data

            error_msg = data if isinstance(data, str) else str(data)
            error_type = parse_error_type(error_msg)

            # 重试时遇到频率限制，等待后再试一次
            if error_type == ErrorType.RATE_LIMIT:
                self.logger.warning(f"批次 {batch_num} 重试触发频率限制，等待 30 秒")
                time.sleep(30)
                wait_for_api('market_snapshot')
                ret, data = self.futu_client.client.get_market_snapshot(valid_stocks)
                if ReturnCode.is_ok(ret):
                    return data
                error_msg = data if isinstance(data, str) else str(data)

            self.logger.warning(f"批次 {batch_num} 重试仍失败: {error_msg}")
            return None

        except Exception as e:
            self.logger.error(f"批次 {batch_num} 重试异常: {e}", exc_info=True)
            return None



    def _get_cache(self, key: str) -> Optional[Dict]:
        """获取缓存数据，不存在或已过期返回 None"""
        if key in self._cache:
            data, expire_time = self._cache[key]
            if time.time() < expire_time:
                return data
            else:
                del self._cache[key]
        return None

    def _set_cache(self, key: str, data: Dict, duration: int):
        """设置缓存数据"""
        expire_time = time.time() + duration
        self._cache[key] = (data, expire_time)

    def calculate_enhanced_heat_scores(
        self, stock_codes: List[str],
        quote_data: Dict = None, kline_data: Dict = None,
        plate_data: Dict = None, use_cache: bool = True
    ) -> Dict[str, Dict[str, Any]]:
        """计算增强热度分（多维度），未启用时降级到基础模式"""
        if not self.enhanced_enabled or not self.enhanced_calculator:
            self.logger.warning("增强热度计算未启用，使用基础模式")
            return self.calculate_realtime_heat_scores(stock_codes, use_cache)

        try:
            self.logger.info(f"使用增强模式计算 {len(stock_codes)} 只股票的热度")

            # 调用增强热度计算器
            enhanced_scores = self.enhanced_calculator.calculate_multi_dimension_heat(
                stock_codes,
                quote_data=quote_data,
                kline_data=kline_data,
                plate_data=plate_data
            )

            self.logger.info(f"增强热度计算完成，成功计算 {len(enhanced_scores)} 只股票")
            return enhanced_scores

        except Exception as e:
            self.logger.error(f"增强热度计算失败: {e}", exc_info=True)
            # 降级到基础模式
            return self.calculate_realtime_heat_scores(stock_codes, use_cache)
