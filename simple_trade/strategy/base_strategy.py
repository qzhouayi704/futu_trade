#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
策略抽象基类

定义所有交易策略的通用接口和基础功能。
所有具体策略都应该继承此基类。
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional

# 数据模型从 strategy_models.py 导入（向后兼容：仍可从此模块导入）
from .strategy_models import StrategyResult, ConditionDetail, TradingConditionResult

# 向后兼容：保持 __all__ 包含所有公开名
__all__ = [
    "BaseStrategy",
    "StrategyResult",
    "ConditionDetail",
    "TradingConditionResult",
]


class BaseStrategy(ABC):
    """
    策略抽象基类
    
    所有交易策略都应该继承此类并实现抽象方法。
    
    使用示例：
    ```python
    class MyStrategy(BaseStrategy):
        @property
        def name(self) -> str:
            return "我的策略"
        
        @property
        def description(self) -> str:
            return "策略描述"
        
        def check_signals(self, stock_code, quote_data, kline_data) -> StrategyResult:
            # 实现策略逻辑
            return StrategyResult(stock_code=stock_code, ...)
    ```
    """
    
    def __init__(self, data_service=None, config: Dict[str, Any] = None):
        """
        初始化策略
        
        Args:
            data_service: 数据服务，用于获取行情数据
            config: 策略配置参数
        """
        self.data_service = data_service
        self.config = config or {}
    
    # ==================== 抽象属性 ====================
    
    @property
    @abstractmethod
    def name(self) -> str:
        """
        策略名称
        
        Returns:
            策略的中文名称
        """
        pass
    
    @property
    @abstractmethod
    def description(self) -> str:
        """
        策略描述
        
        Returns:
            策略的简短描述
        """
        pass
    
    # ==================== 抽象方法 ====================
    
    @abstractmethod
    def check_signals(
        self, 
        stock_code: str, 
        quote_data: Dict[str, Any],
        kline_data: List[Dict[str, Any]]
    ) -> StrategyResult:
        """
        检查交易信号
        
        这是策略的核心方法，实现具体的交易逻辑。
        
        Args:
            stock_code: 股票代码
            quote_data: 实时报价数据，包含 last_price, high_price, low_price 等
            kline_data: K线数据列表，按日期升序排列
            
        Returns:
            StrategyResult: 策略检查结果
        """
        pass
    
    # ==================== 可选覆盖方法 ====================
    
    def get_buy_conditions(self) -> List[str]:
        """
        获取买入条件列表
        
        Returns:
            买入条件的文字描述列表
        """
        return []
    
    def get_sell_conditions(self) -> List[str]:
        """
        获取卖出条件列表
        
        Returns:
            卖出条件的文字描述列表
        """
        return []
    
    def get_required_kline_days(self) -> int:
        """
        获取策略需要的K线天数
        
        Returns:
            需要的最小K线天数
        """
        return 1
    
    def validate_data(
        self, 
        quote_data: Dict[str, Any], 
        kline_data: List[Dict[str, Any]]
    ) -> tuple:
        """
        验证数据是否满足策略要求
        
        Args:
            quote_data: 实时报价数据
            kline_data: K线数据列表
            
        Returns:
            (is_valid, error_message)
        """
        required_days = self.get_required_kline_days()
        
        if not quote_data:
            return False, "缺少实时报价数据"
        
        if len(kline_data) < required_days:
            return False, f"K线数据不足，需要{required_days}天，当前{len(kline_data)}天"
        
        return True, ""
    
    def calculate_signal_strength(self, result: StrategyResult) -> float:
        """
        计算信号强度
        
        子类可以覆盖此方法实现自定义的信号强度计算。
        
        Args:
            result: 策略结果
            
        Returns:
            信号强度 (0.0 - 1.0)
        """
        if result.has_signal:
            return 0.5  # 默认信号强度
        return 0.0
    
    # ==================== 通用方法 ====================
    
    def check_stock_conditions(
        self,
        stock_data: tuple
    ) -> TradingConditionResult:
        """
        检查单个股票的交易条件
        
        提供统一的条件检查接口，子类可以覆盖以自定义行为。
        
        Args:
            stock_data: 股票数据元组 (id, code, name, price, change_percent, volume, high, low, open, plate_name)
            
        Returns:
            TradingConditionResult: 条件检查结果
        """
        # 解析股票数据
        stock_id, code, name, current_price, change_percent, volume, high_price, low_price, open_price, plate_name = stock_data
        
        result = TradingConditionResult(
            stock_code=code,
            stock_name=name or "",
            plate_name=plate_name or "",
            strategy_name=self.name
        )
        
        # 构建报价数据
        quote_data = {
            'code': code,
            'last_price': current_price,
            'high_price': high_price,
            'low_price': low_price,
            'open_price': open_price,
            'change_percent': change_percent,
            'volume': volume
        }
        
        # 检查价格数据
        if not high_price or not low_price:
            result.reason = "缺少价格数据，无法判断"
            result.details.append(ConditionDetail(
                name="数据完整性",
                current_value=f"高:{high_price}, 低:{low_price}",
                target_value="需要完整价格数据",
                passed=False,
                description="需要当日高低价数据进行策略判断"
            ))
            return result
        
        # 获取K线数据
        kline_data = []
        if self.data_service:
            try:
                kline_data = self.data_service.get_kline_data(code, days=self.get_required_kline_days())
            except Exception as e:
                result.reason = f"获取K线数据失败: {e}"
                return result
        
        # 验证数据
        is_valid, error_msg = self.validate_data(quote_data, kline_data)
        if not is_valid:
            result.reason = error_msg
            result.details.append(ConditionDetail(
                name="数据验证",
                current_value=error_msg,
                target_value="数据完整可用",
                passed=False,
                description=error_msg
            ))
            return result
        
        # 检查策略信号
        try:
            strategy_result = self.check_signals(code, quote_data, kline_data)
            result.strategy_result = strategy_result
            
            # 计算信号强度
            strategy_result.signal_strength = self.calculate_signal_strength(strategy_result)
            
            # 构建条件详情
            result.details = self._build_condition_details(strategy_result, quote_data, kline_data)
            
            # 设置结果
            result.condition_passed = strategy_result.has_signal
            if strategy_result.buy_signal:
                result.reason = f"✅ 买入信号触发: {strategy_result.buy_reason}"
            elif strategy_result.sell_signal:
                result.reason = f"✅ 卖出信号触发: {strategy_result.sell_reason}"
            else:
                result.reason = f"❌ 无交易信号: {strategy_result.reason}"
                
        except Exception as e:
            result.reason = f"策略检查异常: {e}"
            result.details.append(ConditionDetail(
                name="错误信息",
                current_value=str(e),
                target_value="正常执行",
                passed=False,
                description="策略执行过程中发生异常"
            ))
        
        return result
    
    def _build_condition_details(
        self,
        strategy_result: StrategyResult,
        quote_data: Dict[str, Any],
        kline_data: List[Dict[str, Any]]
    ) -> List[ConditionDetail]:
        """
        构建条件详情列表
        
        子类可以覆盖此方法自定义详情展示。
        """
        details = []
        
        # 买入条件
        details.append(ConditionDetail(
            name="买入条件",
            current_value=strategy_result.buy_reason[:50] + "..." if len(strategy_result.buy_reason) > 50 else strategy_result.buy_reason,
            target_value=", ".join(self.get_buy_conditions())[:50] or "见策略说明",
            passed=strategy_result.buy_signal,
            description=strategy_result.buy_reason
        ))
        
        # 卖出条件
        details.append(ConditionDetail(
            name="卖出条件",
            current_value=strategy_result.sell_reason[:50] + "..." if len(strategy_result.sell_reason) > 50 else strategy_result.sell_reason,
            target_value=", ".join(self.get_sell_conditions())[:50] or "见策略说明",
            passed=strategy_result.sell_signal,
            description=strategy_result.sell_reason
        ))
        
        # 数据可用性
        details.append(ConditionDetail(
            name="数据可用性",
            current_value=f"K线数据:{len(kline_data)}天",
            target_value=f"≥{self.get_required_kline_days()}天历史数据",
            passed=len(kline_data) >= self.get_required_kline_days(),
            description="需要足够的历史数据进行策略判断"
        ))
        
        # 价格范围
        current_price = quote_data.get('last_price', 0)
        details.append(ConditionDetail(
            name="价格范围",
            current_value=f"{current_price:.2f}" if current_price else "0.00",
            target_value="0.10-1000.00",
            passed=current_price and 0.1 <= current_price <= 1000,
            description="股票价格应在合理范围内"
        ))
        
        return details
    
    def batch_check_conditions(
        self, 
        stocks_data: List[tuple]
    ) -> List[TradingConditionResult]:
        """
        批量检查多个股票的交易条件
        
        Args:
            stocks_data: 股票数据列表
            
        Returns:
            条件检查结果列表
        """
        results = []
        for stock_data in stocks_data:
            try:
                result = self.check_stock_conditions(stock_data)
                results.append(result)
            except Exception as e:
                code = stock_data[1] if len(stock_data) > 1 else "unknown"
                name = stock_data[2] if len(stock_data) > 2 else ""
                results.append(TradingConditionResult(
                    stock_code=code,
                    stock_name=name,
                    strategy_name=self.name,
                    reason=f"检查异常: {e}"
                ))
        return results
    
    def get_strategy_info(self) -> Dict[str, Any]:
        """
        获取策略完整信息
        
        Returns:
            策略信息字典
        """
        return {
            'name': self.name,
            'description': self.description,
            'buy_conditions': self.get_buy_conditions(),
            'sell_conditions': self.get_sell_conditions(),
            'required_kline_days': self.get_required_kline_days(),
            'config': self.config
        }
