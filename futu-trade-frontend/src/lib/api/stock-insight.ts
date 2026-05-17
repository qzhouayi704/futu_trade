/**
 * 个股深度分析 API
 */

// ==================== 类型定义 ====================

export interface CapitalFlowTimeline {
  date: string;
  net_inflow: number;
}

export interface ActivityTrend {
  date: string;
  turnover_rate: number;
  turnover_amount: number;
}

export interface KlinePattern {
  type: string;
  body_ratio: number;
  upper_shadow_ratio: number;
  lower_shadow_ratio: number;
  pattern_name: string;
  pattern_signal: 'bullish' | 'bearish' | 'neutral';
}

export interface Signal {
  label: string;
  source: string;
  reason?: string;
  detail?: string;
  confidence?: number;
  weight?: number;
}

export interface Scenario {
  name: string;
  probability: number;
  type: 'bullish' | 'bearish' | 'neutral';
}

export interface StockTag {
  label: string;
  phase: string;
  atr: number;
  vol_ratio: number;
  avg_amplitude: number;
  avg_turnover_rate: number;
  risk_note: string;
}

export interface KeyLevels {
  prev_high: number;
  prev_low: number;
  prev_close: number;
  support_5d: number;
  resistance_5d: number;
  fib_382: number;
  fib_500: number;
  fib_618: number;
  buy_zone_low: number;
  buy_zone_high: number;
  stop_loss: number;
  vwap_buy_near: number;
  vwap_buy_far: number;
  vwap_sell: number;
}

export interface StockInsightResult {
  stock_code: string;
  stock_name: string;
  last_kline_date: string;
  stock_tag?: StockTag;
  key_levels?: KeyLevels;
  capital_flow: {
    timeline: CapitalFlowTimeline[];
    continuity_days: number;
    trend_text: string;
  };
  capital_score: {
    score: number;
    net_inflow_ratio: number;
    big_order_ratio: number;
    main_net_inflow: number;
  };
  activity: ActivityTrend[];
  kline_pattern: KlinePattern;
  signals: {
    bullish: Signal[];
    bearish: Signal[];
    neutral: Signal[];
    bullish_count: number;
    bearish_count: number;
  };
  verdict: {
    text: string;
    sentiment: string;
    emoji: string;
    bullish_score: number;
    bearish_score: number;
    scenarios: Scenario[];
  };
}

export interface NewsItem {
  title: string;
  date: string;
  summary: string;
  sentiment: 'positive' | 'negative' | 'neutral';
}

export interface StockNewsResult {
  news: NewsItem[];
  key_catalysts: string[];
  risk_factors: string[];
  overall_sentiment: string;
  error?: string | null;
}

// ==================== API 调用 ====================

const API_BASE = '/api/stock-insight';

export async function analyzeStock(
  stockCode: string,
  quickScanResult?: Record<string, unknown>,
  flowSignals?: Record<string, unknown>[],
): Promise<StockInsightResult> {
  const res = await fetch(`${API_BASE}/analyze`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      stock_code: stockCode,
      quick_scan_result: quickScanResult || null,
      flow_signals: flowSignals || null,
    }),
  });
  if (!res.ok) throw new Error(`分析请求失败: ${res.status}`);
  const json = await res.json();
  if (!json.success) throw new Error(json.message || '分析失败');
  return json.data;
}

export async function searchStockNews(
  stockCode: string,
  stockName: string,
): Promise<StockNewsResult> {
  const res = await fetch(`${API_BASE}/news`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      stock_code: stockCode,
      stock_name: stockName,
    }),
  });
  if (!res.ok) throw new Error(`消息面请求失败: ${res.status}`);
  const json = await res.json();
  return json.data || { news: [], key_catalysts: [], risk_factors: [], overall_sentiment: 'neutral' };
}

