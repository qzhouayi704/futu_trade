// 快速扫描 — 日内价位分析 API

const API_BASE = "/api/quick-scan";

export interface QuickScanRequest {
  stock_code: string;
  last_price: number;
  open_price: number;
  prev_close_price: number;
  high_price: number;
  low_price: number;
  change_rate: number;
  turnover_rate: number;
  volume_ratio: number;
  amplitude: number;
  capital_score?: number;
  big_order_buy_ratio?: number;
  main_net_inflow?: number;
  ticker_score?: number;
  ticker_buy_sell_ratio?: number;
  is_position?: boolean;
}

export interface PriceAnalysis {
  anchor_price: number;
  open_type: string;
  buy_target: number;
  buy_target_aggressive: number;
  sell_target: number;
  sell_target_aggressive: number;
  stop_loss: number;
  current_zone: string;
  zone_label: string;
  distance_to_buy_pct: number;
  distance_to_sell_pct: number;
  risk_reward_ratio: number;
  risk_reward_ok: boolean;
  median_dip_pct: number;
  median_rise_pct: number;
  hit_rate_buy: number;
  hit_rate_sell: number;
  support_level: number;
  resistance_level: number;
  today_touched_buy: boolean;
  today_touched_sell: boolean;
  max_loss_pct: number;
}

export interface Indicators {
  kline_position: number;
  kline_level: string;
  capital_score: number;
  capital_signal: string;
  capital_continuity: number;
  volume_ratio: number;
  volume_signal: string;
  ticker_score: number;
  ticker_bias: string;
  total_change_20d: number;
}

export interface QuickScanResult {
  stock_code: string;
  verdict: string;
  verdict_type: "buy" | "sell" | "hold" | "stop" | "neutral" | "insufficient";
  confidence: number;
  action_text: string;
  price_analysis: PriceAnalysis;
  indicators: Indicators;
  confidence_factors: { label: string; impact: string }[];
  warnings: { type: string; text: string }[];
  meta: {
    kline_days: number;
    kline_last_date: string;
    data_sufficient: boolean;
    is_trading_hours: boolean;
    session_hint: string;
  };
}

export async function analyzeStock(
  params: QuickScanRequest
): Promise<QuickScanResult> {
  const res = await fetch(`${API_BASE}/analyze`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });

  if (!res.ok) {
    throw new Error(`分析请求失败: ${res.status}`);
  }

  const json = await res.json();
  if (!json.success) {
    throw new Error(json.message || "分析失败");
  }
  return json.data;
}

export async function batchAnalyze(
  stocks: QuickScanRequest[]
): Promise<QuickScanResult[]> {
  const res = await fetch(`${API_BASE}/batch-analyze`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ stocks }),
  });

  if (!res.ok) {
    throw new Error(`批量分析请求失败: ${res.status}`);
  }

  const json = await res.json();
  if (!json.success) {
    throw new Error(json.message || "批量分析失败");
  }
  return json.data;
}
