#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
交易路由辅助函数和模型

提供交易路由使用的Pydantic模型和辅助函数
"""

from typing import Optional
from pydantic import BaseModel, Field

from ...core.exceptions import ValidationError
from ...core.models import StockInfo


# ==================== Pydantic Models ====================

class ExecuteTradeRequest(BaseModel):
    """执行交易请求"""
    stock_code: str = Field(..., min_length=1, description="股票代码")
    trade_type: str = Field(..., pattern="^(BUY|SELL)$", description="交易类型(BUY/SELL)")
    price: float = Field(..., gt=0, description="交易价格")
    quantity: int = Field(..., gt=0, description="交易数量(必须是100的倍数)")
    signal_id: Optional[int] = Field(None, description="信号ID")

    def validate_quantity(self):
        """验证数量是100的倍数"""
        if self.quantity % 100 != 0:
            raise ValidationError("交易数量必须是100的倍数")


class AddMonitorTaskRequest(BaseModel):
    """添加监控任务请求"""
    stock_code: str = Field(..., min_length=1, description="股票代码")
    stock_name: Optional[str] = Field(None, description="股票名称")
    direction: str = Field(..., pattern="^(BUY|SELL)$", description="交易方向(BUY/SELL)")
    target_price: float = Field(..., gt=0, description="目标价格")
    quantity: int = Field(..., gt=0, description="数量(必须是100的倍数)")
    stop_loss_price: Optional[float] = Field(None, gt=0, description="止损价格")

    def validate_quantity(self):
        """验证数量是100的倍数"""
        if self.quantity % 100 != 0:
            raise ValidationError("数量必须是100的正整数倍")

    def to_stock_info(self) -> StockInfo:
        """转换为 StockInfo 对象"""
        return StockInfo(
            code=self.stock_code,
            name=self.stock_name or self.stock_code
        )


# ==================== Helper Functions ====================

def ensure_trade_service(container):
    """确保交易服务已初始化"""
    if not hasattr(container, 'futu_trade_service') or container.futu_trade_service is None:
        from ...services.trading import FutuTradeService
        container.futu_trade_service = FutuTradeService(
            container.db_manager, container.config
        )
    return container.futu_trade_service


def ensure_monitor_service(container):
    """确保价格监控服务已初始化"""
    if not hasattr(container, 'price_monitor_service') or container.price_monitor_service is None:
        from ...services.alert.price_monitor_service import PriceMonitorService
        container.price_monitor_service = PriceMonitorService(
            container.db_manager, container.config,
            getattr(container, 'futu_trade_service', None)
        )
    return container.price_monitor_service
