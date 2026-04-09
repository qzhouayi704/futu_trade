// 决策助理类型定义

export type HealthLevel = "STRONG" | "NEUTRAL" | "WEAK" | "DANGER";
export type AdviceType =
  | "HOLD"
  | "REDUCE"
  | "CLEAR"
  | "SWAP"
  | "STOP_LOSS"
  | "TAKE_PROFIT"
  | "ADD_POSITION";
export type Urgency = 1 | 5 | 8 | 10;

export interface PositionHealth {
  stock_code: string;
  stock_name: string;
  health_level: HealthLevel;
  score: number;
  profit_pct: number;
  holding_days: number;
  turnover_rate: number;
  amplitude: number;
  volume_ratio: number;
  trend: "UP" | "DOWN" | "SIDEWAYS";
  reasons: string[];
}

export interface DecisionAdvice {
  id: string;
  advice_type: AdviceType;
  advice_type_label: string;
  urgency: Urgency;
  title: string;
  description: string;
  sell_stock_code?: string;
  sell_stock_name?: string;
  sell_price?: number;
  buy_stock_code?: string;
  buy_stock_name?: string;
  buy_price?: number;
  quantity?: number;
  sell_ratio?: number;
  position_health?: PositionHealth;
  created_at: string;
  is_dismissed: boolean;
  ai_analysis?: AIAnalysis;
}

// Gemini 量化分析师输出
export type AnalystAction =
  | "STRONG_BUY"
  | "BUY"
  | "HOLD"
  | "REDUCE"
  | "SELL"
  | "STRONG_SELL"
  | "WAIT";

export interface AIAnalysis {
  catalyst_impact: "Bullish" | "Bearish" | "Neutral";
  smart_money_alignment: "Confirming" | "Diverging" | "Unclear";
  is_priced_in: boolean;
  alpha_signal_score: number; // -1.0 到 1.0
  action: AnalystAction;
  confidence: number; // 0-1
  reasoning: string;
  key_factors: string[];
  risk_warning?: string;
  target_price?: number;
  stop_loss_price?: number;
  time_horizon: "INTRADAY" | "SHORT_TERM";
}

export interface AdvisorSummary {
  total_advices: number;
  critical_count: number;
  high_count: number;
  type_counts: Record<string, number>;
  last_evaluation: string | null;
  position_count: number;
}

export interface AdvisorData {
  advices: DecisionAdvice[];
  summary: AdvisorSummary;
  health: PositionHealth[];
}
