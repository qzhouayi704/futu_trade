#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
富途API类型包装模块

提供市场类型、订阅类型、返回码等枚举的包装，
避免直接依赖富途API导入错误。
"""

# 富途API导入
try:
    from futu import Market, SubType, RET_OK, RET_ERROR
    FUTU_AVAILABLE = True
except ImportError:
    FUTU_AVAILABLE = False
    Market = None
    SubType = None
    RET_OK = None
    RET_ERROR = None


class MarketType:
    """市场类型枚举包装"""

    @staticmethod
    def get_hk_market():
        """获取港股市场枚举"""
        return Market.HK if FUTU_AVAILABLE else None

    @staticmethod
    def get_us_market():
        """获取美股市场枚举"""
        return Market.US if FUTU_AVAILABLE else None

    @staticmethod
    def get_market_by_code(market_code: str):
        """根据市场代码获取市场枚举"""
        if not FUTU_AVAILABLE:
            return None

        if market_code == 'HK':
            return Market.HK
        elif market_code == 'US':
            return Market.US
        else:
            return None


class SubscriptionType:
    """订阅类型包装"""

    @staticmethod
    def get_quote_type():
        """获取报价订阅类型"""
        return SubType.QUOTE if FUTU_AVAILABLE else None


class ReturnCode:
    """返回状态包装"""

    @staticmethod
    def is_ok(ret_code) -> bool:
        """检查返回码是否成功"""
        return FUTU_AVAILABLE and ret_code == RET_OK

    @staticmethod
    def get_ok_code():
        """获取成功返回码"""
        return RET_OK if FUTU_AVAILABLE else None

    @staticmethod
    def get_error_code():
        """获取错误返回码"""
        return RET_ERROR if FUTU_AVAILABLE else None
