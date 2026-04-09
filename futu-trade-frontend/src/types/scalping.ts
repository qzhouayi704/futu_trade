/**
 * 日内超短线交易系统 - TypeScript 类型定义
 *
 * 与后端 Pydantic 模型 (simple_trade/services/scalping/models.py) 一一对应。
 */

// ==================== Socket.IO 事件数据类型 ====================

/** Delta 动量更新（DELTA_UPDATE 事件） */
export interface DeltaUpdateData {
  stock_code: string;
  /** 净动量值（正=买方，负=卖方） */
  delta: number;
  /** 累计成交量 */
  volume: number;
  /** ISO 格式时间戳 */
  timestamp: string;
  /** 累加周期（10 或 60） */
  period_seconds: number;
  /** OHLC 价格（可选，供 K 线蜡烛图渲染） */
  open?: number;
  high?: number;
  low?: number;
  close?: number;
  /** 大单成交量 */
  big_order_volume?: number;
  /** 超大单成交量（≥100万） */
  super_large_volume?: number;
  /** 大单成交量（10万-100万） */
  large_volume?: number;
  /** 中单成交量（2万-10万） */
  medium_volume?: number;
  /** 小单成交量（<2万） */
  small_volume?: number;
  /** 大单主买量 */
  big_buy_volume?: number;
  /** 大单主卖量 */
  big_sell_volume?: number;
}

/** 动能点火事件（MOMENTUM_IGNITION 事件） */
export interface MomentumIgnitionData {
  stock_code: string;
  /** 当前 3 秒窗口成交笔数 */
  current_count: number;
  /** 开盘均值 */
  baseline_avg: number;
  /** 当前倍数 */
  multiplier: number;
  timestamp: string;
}

/** 阻力/支撑线操作类型 */
export type PriceLevelAction = 'create' | 'remove' | 'break';

/** 阻力/支撑方向 */
export type PriceLevelSide = 'resistance' | 'support';

/** 阻力/支撑线事件（PRICE_LEVEL_CREATE/REMOVE/BREAK 事件） */
export interface PriceLevelData {
  stock_code: string;
  price: number;
  /** 挂单存量 */
  volume: number;
  side: PriceLevelSide;
  action: PriceLevelAction;
  timestamp: string;
}

/** POC 更新事件（POC_UPDATE 事件） */
export interface PocUpdateData {
  stock_code: string;
  /** 控制点价格 */
  poc_price: number;
  /** 对应累计成交量 */
  poc_volume: number;
  /** 价位 → 成交量（JSON key 为字符串） */
  volume_profile: Record<string, number>;
  timestamp: string;
}

/** Scalping 信号类型 */
export type ScalpingSignalType = 'breakout_long' | 'support_long';

/** 交易信号事件（SCALPING_SIGNAL 事件） */
export interface ScalpingSignalData {
  stock_code: string;
  signal_type: ScalpingSignalType;
  trigger_price: number;
  /** 仅 support_long 信号 */
  support_price?: number;
  /** 触发条件明细 */
  conditions: string[];
  timestamp: string;
  /** 信号总评分（0-10 分） */
  score?: number;
  /** 评分组成部分 */
  score_components?: {
    delta_score: number;
    ofi_score: number;
    acceleration_score: number;
    vwap_deviation_score: number;
    poc_distance_score: number;
  };
  /** 信号质量等级（high/medium/low） */
  quality_level?: 'high' | 'medium' | 'low';
}

// ==================== 防诱多/诱空事件数据类型（新增） ====================

/** 诱多/诱空类型 */
export type TrapAlertType = 'bull_trap' | 'bear_trap';

/** 诱多/诱空警报事件（TRAP_ALERT 事件） */
export interface TrapAlertData {
  stock_code: string;
  trap_type: TrapAlertType;
  current_price: number;
  /** 诱多=日内高点，诱空=支撑位价格 */
  reference_price: number;
  delta_value: number;
  /** 仅诱空：卖单流量 */
  sell_volume?: number;
  timestamp: string;
}

/** 假突破警报事件（FAKE_BREAKOUT_ALERT 事件） */
export interface FakeBreakoutAlertData {
  stock_code: string;
  breakout_price: number;
  current_price: number;
  velocity_decay_ratio: number;
  survival_seconds: number;
  timestamp: string;
}

/** 真突破确认事件（TRUE_BREAKOUT_CONFIRM 事件） */
export interface TrueBreakoutConfirmData {
  stock_code: string;
  breakout_price: number;
  current_price: number;
  velocity_multiplier: number;
  advance_ticks: number;
  timestamp: string;
}

/** 虚假流动性警报事件（FAKE_LIQUIDITY_ALERT 事件） */
export interface FakeLiquidityAlertData {
  stock_code: string;
  disappear_price: number;
  original_volume: number;
  tracking_duration: number;
  move_path: number[];
  timestamp: string;
}

/** VWAP 超限警报事件（VWAP_EXTENSION_ALERT 事件） */
export interface VwapExtensionAlertData {
  stock_code: string;
  current_price: number;
  vwap_value: number;
  deviation_percent: number;
  dynamic_threshold: number;
  timestamp: string;
}

/** VWAP 恢复正常事件（VWAP_EXTENSION_CLEAR 事件） */
export interface VwapExtensionClearData {
  stock_code: string;
  current_price: number;
  vwap_value: number;
  deviation_percent: number;
  timestamp: string;
}

// ==================== Tick 可信度与止损事件数据类型（新增） ====================

/** 异常大单标记事件（TICK_OUTLIER 事件） */
export interface TickOutlierData {
  stock_code: string;
  price: number;
  volume: number;
  avg_volume: number;
  multiplier: number;
  timestamp: string;
}

/** 止损信号类型 */
export type StopLossSignalType = 'breakout_stop' | 'support_stop';

/** 止损提示事件（STOP_LOSS_ALERT 事件） */
export interface StopLossAlertData {
  stock_code: string;
  signal_type: StopLossSignalType;
  entry_price: number;
  /** 仅 support_stop：支撑位价格 */
  support_price?: number;
  current_price: number;
  drawdown_percent: number;
  timestamp: string;
}

// ==================== 行为模式预警与行动评分数据类型 ====================

/** 行为模式预警事件（PATTERN_ALERT 事件） */
export interface PatternAlertData {
  stock_code: string;
  pattern_type: string;      // fake_rally, fake_drop, vol_stall_top, etc.
  direction: string;         // "bullish" | "bearish" | "neutral"
  title: string;             // 简短标题
  description: string;       // 预警文案
  severity: string;          // "warning" | "danger" | "info"
  score_contribution: number;
  timestamp: string;
}

/** 行动评分信号事件（ACTION_SIGNAL 事件） */
export interface ActionSignalData {
  stock_code: string;
  action: string;            // "long" | "short"
  score: number;
  level: string;             // "watch" | "action"
  components: { name: string; score: number; detail: string }[];
  stop_loss_ref: number | null;
  timestamp: string;
}

// ==================== 连接状态 ====================

/** Scalping 连接状态 */
export interface ScalpingConnectionStatus {
  stock_code: string;
  connected: boolean;
  error?: string;
}
