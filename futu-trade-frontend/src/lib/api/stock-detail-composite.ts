/**
 * 股票详情组合数据 API
 */

const API_BASE = "/api/stock-detail";

export interface PriceLine {
  time: string;
  price: number;
  avg_price: number;
  volume: number;
  turnover: number;
}

export interface TickerStrength {
  time: string;
  buy_volume: number;
  sell_volume: number;
  delta: number;
  ratio: number;
  tick_count: number;
}

export interface BigOrder {
  time: string;
  price: number;
  volume: number;
  turnover: number;
  direction: string;
}

export interface IntradayCompositeData {
  price_line: PriceLine[];
  ticker_strength: TickerStrength[];
  big_orders: BigOrder[];
  stock_code: string;
  trade_date: string;
}

export interface SignalDimension {
  name: string;
  icon: string;
  score: number | null;
  label: string;
}

export interface SignalResonanceData {
  dimensions: SignalDimension[];
  summary: {
    avg_score: number;
    bullish_count: number;
    bearish_count: number;
    neutral_count: number;
    verdict: string;
    conflicts: string[];
  };
  stock_code: string;
}

export interface KlineDeltaCandle {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  delta: number;
  cum_delta: number;
  buy_vol: number;
  sell_vol: number;
}

export interface KlineDeltaData {
  candles: KlineDeltaCandle[];
  stock_code: string;
  count: number;
}

async function fetchJSON<T>(url: string): Promise<{ success: boolean; data: T | null; message?: string }> {
  const res = await fetch(url);
  return res.json();
}

export async function getIntradayComposite(stockCode: string) {
  return fetchJSON<IntradayCompositeData>(`${API_BASE}/intraday-composite/${stockCode}`);
}

export async function getSignalResonance(stockCode: string) {
  return fetchJSON<SignalResonanceData>(`${API_BASE}/signal-resonance/${stockCode}`);
}

export async function getKlineDelta(stockCode: string, limit = 48) {
  return fetchJSON<KlineDeltaData>(`${API_BASE}/kline-delta/${stockCode}?limit=${limit}`);
}
