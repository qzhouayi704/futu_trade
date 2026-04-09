#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
报价服务模块

提供带订阅验证的股票报价获取服务。
在获取报价前验证股票是否已订阅，避免API调用失败。
"""

import logging
from typing import List, Dict, Any, Tuple, Optional

try:
    from futu import RET_OK, RET_ERROR
    FUTU_AVAILABLE = True
except ImportError:
    FUTU_AVAILABLE = False
    RET_OK = 0
    RET_ERROR = -1


class QuoteService:
    """
    报价服务

    职责：
    1. 获取股票实时报价
    2. 在获取前验证订阅状态
    3. 自动过滤未订阅的股票
    """

    def __init__(self, futu_client, subscription_manager):
        """
        初始化报价服务

        Args:
            futu_client: 富途客户端实例
            subscription_manager: 订阅管理器实例
        """
        self._futu_client = futu_client
        self._subscription_manager = subscription_manager
        self.logger = logging.getLogger(__name__)
        self._quote_call_count = 0  # 报价调用计数器

        # 从配置读取日志间隔
        try:
            from ..config.config import ConfigManager
            config = ConfigManager.get_config()
            self._log_interval = config.logging.get('quote_log_interval', 10)
            self._enable_debug = config.logging.get('enable_quote_debug', False)
        except Exception:
            self._log_interval = 10
            self._enable_debug = False

    def get_stock_quote(self, stock_codes: List[str]) -> Tuple[int, Any]:
        """
        获取股票报价（带订阅验证）

        Args:
            stock_codes: 股票代码列表

        Returns:
            tuple: (ret_code, data/error_message)
        """
        if not self._is_available():
            self.logger.warning("获取报价失败: 富途API不可用")
            return RET_ERROR, "富途API不可用"

        if not stock_codes:
            self.logger.warning("获取报价: 股票代码列表为空")
            return RET_ERROR, "股票代码列表为空"

        # 过滤出已订阅的股票
        subscribed_codes = self._filter_subscribed(stock_codes)

        if not subscribed_codes:
            # 改为 DEBUG 级别，因为这是正常的过滤行为（活跃度筛选后反订阅的股票）
            self.logger.debug(f"过滤后无可用股票，原始请求: {len(stock_codes)} 只")
            return RET_ERROR, "所有请求的股票均未订阅"

        # 记录被过滤的股票
        filtered_count = len(stock_codes) - len(subscribed_codes)
        if filtered_count > 0:
            # 只在过滤比例较高时记录 INFO
            filter_ratio = filtered_count / len(stock_codes)
            if filter_ratio > 0.3:
                self.logger.info(f"过滤了 {filtered_count}/{len(stock_codes)} 只未订阅股票")
            else:
                self.logger.debug(f"过滤了 {filtered_count} 只未订阅股票")

        return self._fetch_quote(subscribed_codes)

    def _is_available(self) -> bool:
        """检查服务是否可用"""
        return (FUTU_AVAILABLE and
                self._futu_client is not None and
                self._futu_client.is_available())

    def _filter_subscribed(self, stock_codes: List[str]) -> List[str]:
        """过滤出已订阅的股票"""
        return [
            code for code in stock_codes
            if self._subscription_manager.is_subscribed(code)
        ]

    def _fetch_quote(self, stock_codes: List[str]) -> Tuple[int, Any]:
        """实际获取报价"""
        try:
            self._quote_call_count += 1

            # 节流日志输出
            if self._enable_debug or (self._quote_call_count % self._log_interval == 1):
                self.logger.debug(f"正在获取 {len(stock_codes)} 只股票的报价 (第{self._quote_call_count}次)")

            ret, data = self._futu_client.client.get_stock_quote(stock_codes)

            if ret == RET_OK:
                if data is not None and not data.empty:
                    if self._enable_debug or (self._quote_call_count % self._log_interval == 1):
                        self.logger.debug(f"成功获取 {len(data)} 只股票的报价")
                return ret, data

            # 记录失败信息
            error_str = str(data)
            is_subscribe_error = 'subscribe' in error_str.lower() or '订阅' in error_str

            if is_subscribe_error:
                self.logger.warning(f"获取报价失败(订阅问题): {error_str[:100]}")
            else:
                self.logger.warning(f"获取报价失败: {error_str[:100]}")

            return ret, data

        except Exception as e:
            self.logger.error(f"获取股票报价异常: {type(e).__name__}: {e}")
            return RET_ERROR, str(e)
