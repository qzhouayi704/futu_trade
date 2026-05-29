// AI 智选 API 封装

import apiClient from "./client";

export interface SmartPickStock {
  code: string;
  name: string;
  change_rate: number;
  turnover_rate: number;
  turnover: number;
  volume_ratio: number;
  amplitude: number;
  capital_signal: string;
  capital_score: number;
  main_net_inflow: number;
  big_order_buy_ratio: number;
  ticker_buy_sell_ratio: number;
  consensus_score: number;
  consensus_verdict: string;
  is_position: boolean;
}

export interface SmartPickItem {
  code: string;
  name: string;
  action: "STRONG_BUY" | "BUY";
  confidence: number;
  reasoning: string;
  key_signal: string;
  risk: string;
  target_price: number | null;
  stop_loss_price: number | null;
}

export interface SmartPickResult {
  picks: SmartPickItem[];
  market_summary: string;
  skip_reason: string;
}

export async function smartPickStocks(
  stocks: SmartPickStock[]
): Promise<{ success: boolean; data?: SmartPickResult; message?: string }> {
  return apiClient.post("/ai-analysis/smart-pick", {
    stocks,
  }, { timeout: 120000 });
}
