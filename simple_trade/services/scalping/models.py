"""
日内超短线交易系统 - Pydantic 数据模型

定义 Scalping Engine 使用的所有输入数据模型和 WebSocket 推送事件数据模型。
"""

from pydantic import BaseModel
from enum import Enum
from typing import Optional


# ==================== 输入数据 ====================


class TickDirection(str, Enum):
    """成交方向"""
    BUY = "buy"        # 主动买入（成交价 = Ask）
    SELL = "sell"      # 主动卖出（成交价 = Bid）
    NEUTRAL = "neutral"


class TickData(BaseModel):
    """逐笔成交数据"""
    stock_code: str
    price: float
    volume: int
    direction: TickDirection
    timestamp: float          # Unix 时间戳（毫秒）
    ask_price: float          # 卖一价
    bid_price: float          # 买一价


class OrderBookLevel(BaseModel):
    """盘口单档"""
    price: float
    volume: int
    order_count: int


class OrderBookData(BaseModel):
    """十档盘口数据"""
    stock_code: str
    ask_levels: list[OrderBookLevel]   # 卖方 10 档
    bid_levels: list[OrderBookLevel]   # 买方 10 档
    timestamp: float


# ==================== WebSocket 推送事件数据 ====================


class DeltaUpdateData(BaseModel):
    """Delta 动量更新（DELTA_UPDATE 事件）"""
    stock_code: str
    delta: float              # 净动量值（正=买方，负=卖方）
    volume: int               # 累计成交量
    timestamp: str            # ISO 格式时间戳
    period_seconds: int       # 累加周期（10 或 60）
    # OHLC 价格（可选，供前端渲染 K 线蜡烛图）
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None
    # 大单成交量（单笔成交额 > 10万的成交量合计）
    big_order_volume: int = 0
    # 四级订单分类成交量
    super_large_volume: int = 0   # 超大单（≥100万）
    large_volume: int = 0         # 大单（10万-100万）
    medium_volume: int = 0        # 中单（2万-10万）
    small_volume: int = 0         # 小单（<2万）
    # 大单买卖方向
    big_buy_volume: int = 0       # 大单主买量（超大单+大单）
    big_sell_volume: int = 0      # 大单主卖量（超大单+大单）


class MomentumIgnitionData(BaseModel):
    """动能点火事件（MOMENTUM_IGNITION 事件）"""
    stock_code: str
    current_count: int        # 当前 3 秒窗口成交笔数
    baseline_avg: float       # 开盘均值
    multiplier: float         # 当前倍数
    timestamp: str


class PriceLevelAction(str, Enum):
    """阻力/支撑线操作类型"""
    CREATE = "create"
    REMOVE = "remove"
    BREAK = "break"


class PriceLevelSide(str, Enum):
    """阻力/支撑方向"""
    RESISTANCE = "resistance"  # 阻力（卖方巨单）
    SUPPORT = "support"        # 支撑（买方巨单）


class PriceLevelData(BaseModel):
    """阻力/支撑线事件（PRICE_LEVEL_CREATE/REMOVE/BREAK 事件）"""
    stock_code: str
    price: float
    volume: int               # 挂单存量
    side: PriceLevelSide
    action: PriceLevelAction
    timestamp: str


class PocUpdateData(BaseModel):
    """POC 更新事件（POC_UPDATE 事件）"""
    stock_code: str
    poc_price: float          # 控制点价格
    poc_volume: int           # 对应累计成交量
    poc_buy_ratio: float = 0.5  # POC 价位的买入占比
    volume_profile: dict[str, int]  # 价位 → 成交量（JSON key 为字符串）
    timestamp: str


class ScalpingSignalType(str, Enum):
    """Scalping 信号类型"""
    BREAKOUT_LONG = "breakout_long"      # 动能突破，做多
    SUPPORT_LONG = "support_long"        # 支撑有效，试多
    EXIT_DELTA_REVERSAL = "exit_delta_reversal"  # Delta 反转平仓
    EXIT_TIME_DECAY = "exit_time_decay"          # 时间衰减平仓


class ScalpingSignalData(BaseModel):
    """交易信号事件（SCALPING_SIGNAL 事件）"""
    stock_code: str
    signal_type: ScalpingSignalType
    trigger_price: float
    support_price: Optional[float] = None  # 仅 support_long 信号
    conditions: list[str]     # 触发条件明细
    timestamp: str
    # 新增：信号评分相关字段
    score: Optional[int] = None  # 总评分（0-10 分）
    score_components: Optional[dict] = None  # 评分组成部分
    quality_level: Optional[str] = None  # 信号质量等级（high/medium/low）


# ==================== 防诱多/诱空事件数据（新增） ====================


class TrapAlertType(str, Enum):
    """诱多/诱空类型"""
    BULL_TRAP = "bull_trap"
    BEAR_TRAP = "bear_trap"


class TrapAlertData(BaseModel):
    """诱多/诱空警报事件（TRAP_ALERT 事件）"""
    stock_code: str
    trap_type: TrapAlertType
    current_price: float
    reference_price: float    # 诱多=日内高点，诱空=支撑位价格
    delta_value: float
    sell_volume: Optional[int] = None  # 仅诱空
    timestamp: str


class FakeBreakoutAlertData(BaseModel):
    """假突破警报事件（FAKE_BREAKOUT_ALERT 事件）"""
    stock_code: str
    breakout_price: float
    current_price: float
    velocity_decay_ratio: float
    survival_seconds: float
    timestamp: str


class TrueBreakoutConfirmData(BaseModel):
    """真突破确认事件（TRUE_BREAKOUT_CONFIRM 事件）"""
    stock_code: str
    breakout_price: float
    current_price: float
    velocity_multiplier: float
    advance_ticks: int
    timestamp: str


class FakeLiquidityAlertData(BaseModel):
    """虚假流动性警报事件（FAKE_LIQUIDITY_ALERT 事件）"""
    stock_code: str
    disappear_price: float
    original_volume: int
    tracking_duration: float
    move_path: list[float]
    timestamp: str


class VwapExtensionAlertData(BaseModel):
    """VWAP 超限警报事件（VWAP_EXTENSION_ALERT 事件）"""
    stock_code: str
    current_price: float
    vwap_value: float
    deviation_percent: float
    dynamic_threshold: float
    timestamp: str


class VwapExtensionClearData(BaseModel):
    """VWAP 恢复正常事件（VWAP_EXTENSION_CLEAR 事件）"""
    stock_code: str
    current_price: float
    vwap_value: float
    deviation_percent: float
    timestamp: str


# ==================== Tick 可信度与止损事件数据（新增） ====================


class TickOutlierData(BaseModel):
    """异常大单标记事件（TICK_OUTLIER 事件）"""
    stock_code: str
    price: float
    volume: int
    avg_volume: float
    multiplier: float
    timestamp: str


class StopLossSignalType(str, Enum):
    """止损信号类型"""
    BREAKOUT_STOP = "breakout_stop"
    SUPPORT_STOP = "support_stop"


class StopLossAlertData(BaseModel):
    """止损提示事件（STOP_LOSS_ALERT 事件）"""
    stock_code: str
    signal_type: StopLossSignalType
    entry_price: float
    support_price: Optional[float] = None
    current_price: float
    drawdown_percent: float
    timestamp: str


# ==================== 平仓配置 ====================


class ExitConfig(BaseModel):
    """Scalping 平仓参数配置"""
    max_hold_seconds: float = 120.0       # 最大持仓时间（秒）
    max_loss_ticks: int = 10              # 最大亏损 Tick 数
    delta_reversal_threshold: float = 1.0  # Delta 反转阈值（均值倍数）
