// 资金流向信号 API

import apiClient from "./client";
import type { ApiResponse } from "@/types";

export interface FlowRule {
  rule_id: string;
  rule_name: string;
  signal_type: "BUY" | "SELL" | "ALERT";
  cooldown: number;
  condition: string;
  suggestion: string;
  priority: "high" | "medium" | "low";
}

export interface FlowSignalRecord {
  id: number;
  rule_id: string;
  rule_name: string;
  stock_code: string;
  stock_name: string;
  signal_type: "BUY" | "SELL" | "ALERT";
  price: number;
  reason: string;
  confidence: number;
  priority: string;
  action_suggestion: string;
  created_at: string;
}

export interface FlowRulesResponse {
  rules: FlowRule[];
  engine_enabled: boolean;
  vwap_tracking: number;
}

export interface FlowHistoryResponse {
  signals: FlowSignalRecord[];
  total: number;
}

/** 按股票代码分组的信号映射（供市场扫描使用） */
export type FlowSignalMap = Record<string, FlowSignalRecord[]>;

export const flowSignalApi = {
  // 获取规则总览
  getRules: async (): Promise<ApiResponse<FlowRulesResponse>> => {
    return apiClient.get("/flow-signals/rules");
  },

  // 获取信号历史
  getHistory: async (params?: {
    limit?: number;
    signal_type?: string;
    stock_code?: string;
  }): Promise<ApiResponse<FlowHistoryResponse>> => {
    const searchParams = new URLSearchParams();
    if (params?.limit) searchParams.set("limit", String(params.limit));
    if (params?.signal_type) searchParams.set("signal_type", params.signal_type);
    if (params?.stock_code) searchParams.set("stock_code", params.stock_code);
    const query = searchParams.toString();
    return apiClient.get(`/flow-signals/history${query ? `?${query}` : ""}`);
  },

  // 获取当天所有信号（按股票分组，供市场扫描页面使用）
  getTodayBatch: async (): Promise<FlowSignalMap> => {
    try {
      const res: ApiResponse<FlowSignalMap> = await apiClient.get("/flow-signals/today-batch");
      return res.success ? (res.data || {}) : {};
    } catch {
      return {};
    }
  },

  // 获取当天日线级策略信号（按股票分组，供市场扫描"判定"列优先显示）
  getTradeSignalsBatch: async (): Promise<TradeSignalMap> => {
    try {
      const res: ApiResponse<TradeSignalMap> = await apiClient.get("/flow-signals/trade-signals-batch");
      return res.success ? (res.data || {}) : {};
    } catch {
      return {};
    }
  },

  // 获取全部交易规则（三大体系）
  getAllRules: async (): Promise<ApiResponse<AllRulesResponse>> => {
    return apiClient.get("/flow-signals/all-rules");
  },
};

/** 日线级策略信号 */
export interface TradeSignalRecord {
  signal_type: "BUY" | "SELL";
  signal_price: number;
  condition_text: string;
  strategy_id: string;
  strategy_name: string;
  created_at: string;
  stock_name: string;
}

/** 按股票代码分组的策略信号映射 */
export type TradeSignalMap = Record<string, TradeSignalRecord[]>;

// ==================== 全部交易规则类型 ====================

export interface RiskBasicRule {
  name: string;
  type: string;
  description: string;
  default_value: string;
  urgency: number;
  liquidity_adaptive: Record<string, string> | null;
}

export interface CoordinatorLevel {
  priority: number;
  name: string;
  description: string;
  urgency: number;
}

export interface DynamicDimension {
  name: string;
  weight: string;
  description: string;
}

export interface RiskRules {
  basic_rules: RiskBasicRule[];
  coordinator_levels: CoordinatorLevel[];
  dynamic_stop_loss: {
    dimensions: DynamicDimension[];
    safety_bounds: Record<string, Record<string, string>>;
    liquidity_bounds: Record<string, { stop_loss: string; take_profit: string; label: string }>;
  };
}

export interface StrategyRules {
  strategy_name: string;
  preset_name: string;
  buy_conditions: string[];
  sell_conditions: string[];
  stop_loss_conditions: string[];
  parameters: Record<string, number>;
}

export interface AllRulesResponse {
  flow_rules: FlowRule[];
  risk_rules: RiskRules;
  strategy_rules: StrategyRules;
  engine_enabled: boolean;
}
