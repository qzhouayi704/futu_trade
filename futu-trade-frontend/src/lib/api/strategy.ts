// 策略 API

import apiClient from "./client";
import type { ApiResponse, Strategy, StrategyPreset } from "@/types";

export const strategyApi = {
  // 获取所有可用策略
  getStrategies: async (): Promise<ApiResponse<Strategy[]>> => {
    return apiClient.get("/strategy/list");
  },

  // 获取当前策略的预设
  getPresets: async (strategyId?: string): Promise<ApiResponse<{
    strategy: string;
    presets: StrategyPreset[];
    active_preset: string;
  }>> => {
    return apiClient.get("/strategy/presets", {
      params: strategyId ? { strategy_id: strategyId } : undefined,
    });
  },

  // 获取当前激活的策略
  getActiveStrategy: async (): Promise<
    ApiResponse<{
      strategy_id: string;
      strategy_name: string;
      preset_name: string;
    }>
  > => {
    return apiClient.get("/strategy/active");
  },

  // 获取当前策略的详细指标
  getStrategyIndicators: async (): Promise<
    ApiResponse<{
      strategy_id: string;
      strategy_name: string;
      strategy_description: string;
      preset_name: string;
      preset_description: string;
      parameters: Record<string, any>;
      buy_conditions: string[];
      sell_conditions: string[];
      stop_loss_conditions: string[];
    }>
  > => {
    return apiClient.get("/strategy/indicators");
  },

  // 切换当前策略
  switchStrategy: async (strategyId: string): Promise<ApiResponse> => {
    return apiClient.post("/strategy/active/strategy", { strategy_id: strategyId });
  },

  // 切换当前预设
  switchPreset: async (presetName: string): Promise<ApiResponse> => {
    return apiClient.post("/strategy/active/preset", { preset_name: presetName });
  },

  // 获取板块强势度排名
  getPlateStrength: async (): Promise<
    ApiResponse<{
      plates: Array<{
        plate_code: string;
        plate_name: string;
        market: string;
        strength_score: number;
        up_stock_ratio: number;
        avg_change_pct: number;
        leader_count: number;
        total_stocks: number;
      }>;
      count: number;
    }>
  > => {
    return apiClient.get("/strategy/aggressive/plate-strength");
  },
};
