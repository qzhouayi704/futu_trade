#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
市场时间判断工具
"""

import logging
from datetime import datetime, time, timezone, timedelta
from typing import List, Optional


class MarketTimeHelper:
    """市场时间判断助手"""
    
    # 强制市场覆盖（用于测试），设置后忽略实际交易时间
    # 可选值: None（不覆盖）, 'HK', 'US'
    _force_market: Optional[str] = None
    
    # 港股交易时间（北京时间）
    HK_MORNING_START = time(9, 30)
    HK_MORNING_END = time(12, 0)
    HK_AFTERNOON_START = time(13, 0)
    HK_AFTERNOON_END = time(16, 0)
    
    # 美股交易时间（北京时间）
    # 夏令时（3月第二个周日 - 11月第一个周日）
    US_SUMMER_START = time(21, 30)
    US_SUMMER_END = time(4, 0)  # 次日
    # 冬令时
    US_WINTER_START = time(22, 30)
    US_WINTER_END = time(5, 0)  # 次日
    
    @classmethod
    def set_force_market(cls, market: str):
        """强制设置活跃市场（用于测试），忽略实际交易时间判断"""
        if market not in ('HK', 'US'):
            raise ValueError(f"无效市场: {market}，仅支持 'HK' 或 'US'")
        cls._force_market = market
        logging.warning(f"[市场覆盖] 已强制设置活跃市场为: {market}")
    
    @classmethod
    def clear_force_market(cls):
        """清除强制市场设置，恢复正常的交易时间判断"""
        cls._force_market = None
        logging.warning("[市场覆盖] 已清除强制市场设置，恢复正常判断")
    
    @staticmethod
    def get_current_active_markets(current_time: Optional[datetime] = None) -> List[str]:
        """
        获取当前活跃的市场
        
        Args:
            current_time: 当前时间，默认使用系统当前时间
            
        Returns:
            活跃市场列表，可能的值：['HK'], ['US'], ['HK', 'US']
        """
        # 如果设置了强制市场，直接返回
        if MarketTimeHelper._force_market:
            return [MarketTimeHelper._force_market]
        
        if current_time is None:
            current_time = datetime.now()
        
        active_markets = []
        current_time_only = current_time.time()
        
        # 检查港股市场
        hk_trading = MarketTimeHelper._is_hk_trading_time(current_time_only)
        if hk_trading:
            active_markets.append('HK')
            
        # 检查美股市场
        us_trading = MarketTimeHelper._is_us_trading_time(current_time, current_time_only)
        if us_trading:
            active_markets.append('US')
        
        # 记录调试日志
        logging.debug(f"[市场判断] 时间={current_time_only}, 港股交易={hk_trading}, 美股交易={us_trading}, 活跃市场={active_markets}")
        
        # 如果没有活跃市场，根据当前时间智能选择
        if not active_markets:
            weekday = current_time.weekday()  # 0=周一, 6=周日
            hour = current_time_only.hour
            
            # 智能选择逻辑：
            # 1. 港股收盘后(16:00后)到次日港股开盘前(9:30前)，优先选择美股
            # 2. 周末优先选择美股
            # 3. 其他时间选择港股
            
            if weekday >= 5:  # 周末
                active_markets.append('US')
            elif hour >= 16 or hour < 9:  # 港股休市时段
                # 16:00-09:30 是港股休市时段，此时优先美股
                active_markets.append('US')
            else:
                # 港股休市但在白天时段（如 9:00-9:30 或 12:00-13:00）
                active_markets.append('HK')
            
            logging.debug(f"[市场判断] 后备选择: weekday={weekday}, hour={hour}, 选择={active_markets}")
        
        return active_markets
    
    @staticmethod
    def _is_hk_trading_time(current_time: time) -> bool:
        """检查是否为港股交易时间"""
        return (MarketTimeHelper.HK_MORNING_START <= current_time <= MarketTimeHelper.HK_MORNING_END or
                MarketTimeHelper.HK_AFTERNOON_START <= current_time <= MarketTimeHelper.HK_AFTERNOON_END)
    
    @staticmethod
    def _is_us_trading_time(current_datetime: datetime, current_time: time) -> bool:
        """检查是否为美股交易时间"""
        # 简化处理：根据月份判断是否为夏令时
        month = current_datetime.month
        is_summer_time = 3 <= month <= 10  # 3月到10月视为夏令时
        
        if is_summer_time:
            # 夏令时：21:30-次日04:00
            if current_time >= MarketTimeHelper.US_SUMMER_START:
                return True
            elif current_time <= MarketTimeHelper.US_SUMMER_END:
                return True
        else:
            # 冬令时：22:30-次日05:00
            if current_time >= MarketTimeHelper.US_WINTER_START:
                return True
            elif current_time <= MarketTimeHelper.US_WINTER_END:
                return True
        
        return False
    
    @staticmethod
    def get_primary_market(current_time: Optional[datetime] = None) -> str:
        """
        获取当前的主要市场
        
        Args:
            current_time: 当前时间，默认使用系统当前时间
            
        Returns:
            主要市场代码：'HK' 或 'US'
        """
        active_markets = MarketTimeHelper.get_current_active_markets(current_time)
        
        if not active_markets:
            return 'HK'  # 默认港股
        
        # 如果有多个活跃市场，优先选择港股
        if 'HK' in active_markets:
            return 'HK'
        else:
            return active_markets[0]
    
    @staticmethod
    def get_market_status_info(current_time: Optional[datetime] = None) -> dict:
        """
        获取市场状态信息
        
        Args:
            current_time: 当前时间，默认使用系统当前时间
            
        Returns:
            市场状态信息字典
        """
        if current_time is None:
            current_time = datetime.now()
            
        active_markets = MarketTimeHelper.get_current_active_markets(current_time)
        primary_market = MarketTimeHelper.get_primary_market(current_time)
        current_time_only = current_time.time()
        
        return {
            'current_time': current_time.strftime('%H:%M:%S'),
            'active_markets': active_markets,
            'primary_market': primary_market,
            'hk_trading': MarketTimeHelper._is_hk_trading_time(current_time_only),
            'us_trading': MarketTimeHelper._is_us_trading_time(current_time, current_time_only),
            'weekday': current_time.weekday(),
            'is_weekend': current_time.weekday() >= 5
        }
    
    @staticmethod
    def should_subscribe_market(market: str, current_time: Optional[datetime] = None) -> bool:
        """
        判断是否应该订阅指定市场的股票
        
        Args:
            market: 市场代码 'HK' 或 'US'
            current_time: 当前时间，默认使用系统当前时间
            
        Returns:
            是否应该订阅该市场
        """
        active_markets = MarketTimeHelper.get_current_active_markets(current_time)
        return market in active_markets
    
    @staticmethod
    def log_market_info(current_time: Optional[datetime] = None):
        """记录当前市场状态信息"""
        status_info = MarketTimeHelper.get_market_status_info(current_time)
        
        logging.info(f"当前时间: {status_info['current_time']}")
        logging.info(f"活跃市场: {', '.join(status_info['active_markets']) if status_info['active_markets'] else '无'}")
        logging.info(f"主要市场: {status_info['primary_market']}")
        logging.info(f"港股交易中: {'是' if status_info['hk_trading'] else '否'}")
        logging.info(f"美股交易中: {'是' if status_info['us_trading'] else '否'}")
        logging.info(f"是否周末: {'是' if status_info['is_weekend'] else '否'}")


    @staticmethod
    def get_market_today(market: str) -> str:
        """
        获取指定市场的当前日期（考虑时差）
        
        用于K线数据的日期过滤，确保不同市场使用正确的"今天"日期。
        
        Args:
            market: 市场代码 'HK' 或 'US'
        
        Returns:
            YYYY-MM-DD 格式的日期字符串
        """
        if market == 'US':
            # 美东时间 = UTC - 5小时（冬令时）或 UTC - 4小时（夏令时）
            # 简化处理：使用 UTC - 5小时
            us_tz = timezone(timedelta(hours=-5))
            return datetime.now(us_tz).strftime('%Y-%m-%d')
        else:
            # 港股用北京时间 = UTC + 8小时
            hk_tz = timezone(timedelta(hours=8))
            return datetime.now(hk_tz).strftime('%Y-%m-%d')
    
    @staticmethod
    def get_market_from_code(stock_code: str) -> str:
        """
        从股票代码判断市场
        
        Args:
            stock_code: 股票代码，如 'HK.00700' 或 'US.AAPL'
        
        Returns:
            市场代码 'HK' 或 'US'
        """
        if stock_code.startswith('US.'):
            return 'US'
        elif stock_code.startswith('HK.'):
            return 'HK'
        else:
            # 默认港股
            return 'HK'
    
    @staticmethod
    def is_any_market_trading(current_time: Optional[datetime] = None) -> bool:
        """
        检查是否有任何市场正在交易
        
        Args:
            current_time: 当前时间，默认使用系统当前时间
            
        Returns:
            True 如果有市场正在交易，False 表示所有市场都已收盘
        """
        if current_time is None:
            current_time = datetime.now()
        
        current_time_only = current_time.time()
        weekday = current_time.weekday()
        
        # 周末检查美股（美股周五晚上有交易，北京时间周六凌晨）
        if weekday == 5:  # 周六
            # 周六凌晨可能是美股周五的延续
            if current_time_only <= time(5, 0):
                return True
            return False
        elif weekday == 6:  # 周日
            return False
        
        # 检查港股
        if MarketTimeHelper._is_hk_trading_time(current_time_only):
            return True
        
        # 检查美股
        if MarketTimeHelper._is_us_trading_time(current_time, current_time_only):
            return True
        
        return False


# 便捷函数
def get_current_primary_market() -> str:
    """获取当前主要市场"""
    return MarketTimeHelper.get_primary_market()


def get_current_active_markets() -> List[str]:
    """获取当前活跃市场列表"""
    return MarketTimeHelper.get_current_active_markets()


def should_subscribe_hk() -> bool:
    """是否应该订阅港股"""
    return MarketTimeHelper.should_subscribe_market('HK')


def should_subscribe_us() -> bool:
    """是否应该订阅美股"""
    return MarketTimeHelper.should_subscribe_market('US')
