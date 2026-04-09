// 价格位置分析 API

import apiClient from "./client";
import type { ApiResponse } from "@/types";

export interface ZoneStats {
  count: number;
  frequency_pct: number;
  rise_stats: {
    mean: number;
    median: number;
    std: number;
    p25: number;
    p75: number;
    min: number;
    max: number;
  };
  drop_stats: {
    mean: number;
    median: number;
    std: number;
    p25: number;
    p75: number;
    min: number;
    max: number;
  };
}

export interface BestParams {
  buy_dip_pct: number;
  sell_rise_pct: number;
  stop_loss_pct: number;
  profit_spread: number;
  avg_net_profit: number;
  win_rate: number;
  trades_count: number;
  stop_loss_rate: number;
  searched_combos: number;
  composite_score?: number;
  degraded?: boolean;
}

export interface TradeSummary {
  total_trades: number;
  win_count: number;
  win_rate: number;
  avg_profit: number;
  avg_net_profit: number;
  max_profit: number;
  max_loss: number;
  stop_loss_count: number;
  stop_loss_rate: number;
}

export interface LastDayInfo {
  date: string;
  prev_close: number;
  open_price: number;
  high_price: number;
  low_price: number;
  close_price: number;
  zone: string;
  price_position: number;
  open_type: string;
  open_gap_pct: number;
}

export interface OpenTypeStats {
  count: number;
  pct: number;
}

export interface OpenTypeParam {
  enabled: boolean;
  anchor: string;
  buy_dip_pct?: number;
  sell_rise_pct?: number;
  stop_loss_pct?: number;
  avg_net_profit?: number;
  win_rate?: number;
  trades_count?: number;
  recommendation?: string;
}

export interface AnalysisResult {
  stock_code: string;
  metrics_count: number;
  zone_stats: Record<string, ZoneStats>;
  best_params: Record<string, BestParams>;
  trade_summary: TradeSummary;
  last_day_info?: LastDayInfo;
  open_type_stats?: Record<string, OpenTypeStats>;
  open_type_params?: Record<string, OpenTypeParam>;
  gap_threshold?: number;
}

export interface AnalysisTask {
  task_id: string;
  stock_code: string;
  status: "started" | "downloading" | "analyzing" | "optimizing" | "completed" | "error";
  progress: string;
  result: AnalysisResult | null;
  error: string | null;
}

export interface AutoTradeTask {
  stock_code: string;
  quantity: number;
  zone: string;
  buy_dip_pct: number;
  sell_rise_pct: number;
  stop_loss_pct: number;
  prev_close: number;
  buy_target: number;
  sell_target: number;
  stop_price: number;
  status: "waiting_buy" | "bought" | "completed" | "stop_loss" | "stopped";
  buy_price_actual: number;
  sell_price_actual: number;
  created_at: string;
  updated_at: string;
  message: string;
}

export const analysisApi = {
  // 启动分析
  startAnalysis: async (stockCode: string): Promise<ApiResponse<{ task_id: string; stock_code: string }>> => {
    return apiClient.post("/analysis/analyze", { stock_code: stockCode });
  },

  // 查询分析状态
  getAnalysisStatus: async (taskId: string): Promise<ApiResponse<AnalysisTask>> => {
    return apiClient.get(`/analysis/analyze/status/${taskId}`);
  },

  // 启动自动交易
  startAutoTrade: async (params: {
    stock_code: string;
    quantity: number;
    zone: string;
    buy_dip_pct: number;
    sell_rise_pct: number;
    stop_loss_pct: number;
    prev_close: number;
    open_type_params?: Record<string, { buy_dip_pct: number; sell_rise_pct: number; stop_loss_pct: number }>;
    gap_threshold?: number;
  }): Promise<ApiResponse<AutoTradeTask>> => {
    return apiClient.post("/analysis/auto-trade/start", params);
  },

  // 停止自动交易
  stopAutoTrade: async (stockCode: string): Promise<ApiResponse> => {
    return apiClient.post("/analysis/auto-trade/stop", { stock_code: stockCode });
  },

  // 查询所有自动交易状态
  getAutoTradeStatus: async (): Promise<ApiResponse<AutoTradeTask[]>> => {
    return apiClient.get("/analysis/auto-trade/status");
  },
};
