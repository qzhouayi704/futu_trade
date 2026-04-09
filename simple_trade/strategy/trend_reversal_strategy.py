"""向后兼容：趋势反转策略已迁移到 trend_reversal/ 子模块"""

# 保持向后兼容，所有导出从新模块重导出
from .trend_reversal.models import TrendAnalysis, StopLossCheck  # noqa: F401
from .trend_reversal.strategy import TrendReversalStrategy  # noqa: F401
from .trend_reversal.analysis import (  # noqa: F401
    analyze_trend,
    analyze_plate_sentiment,
    adjust_signal_by_sentiment,
)
