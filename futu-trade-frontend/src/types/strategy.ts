// 策略相关类型定义

export interface Strategy {
  id: string;
  name: string;
  description: string;
  presets: StrategyPreset[];
}

export interface StrategyPreset {
  name: string;
  description: string;
  params: Record<string, any>;
}

export interface StrategyCondition {
  stock_code: string;
  stock_name: string;
  condition_type: string;
  condition_text: string;
  is_met: boolean;
  details: string;
}

export interface TradingCondition {
  stock_code: string;
  stock_name: string;
  last_price: number;
  change_rate: number;
  buy_conditions: StrategyCondition[];
  sell_conditions: StrategyCondition[];
  can_buy: boolean;
  can_sell: boolean;
}

// ==================== 多策略类型 ====================

export interface EnabledStrategy {
  strategy_id: string;
  strategy_name: string;
  preset_name: string;
  signal_count_buy: number;
  signal_count_sell: number;
}

export interface EnabledStrategiesResponse {
  enabled_strategies: EnabledStrategy[];
  auto_trade_strategy: string | null;
}

export interface SignalsByStrategy {
  [strategyId: string]: StrategySignalItem[];
}

export interface StrategySignalItem {
  stock_code: string;
  stock_name: string;
  signal_type: "BUY" | "SELL";
  price: number;
  reason: string;
  timestamp: string;
  strategy_id: string;
  strategy_name: string;
  preset_name: string;
}
