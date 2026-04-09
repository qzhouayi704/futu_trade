// 多策略管理 API

import apiClient from "./client";
import type {
  ApiResponse,
  EnabledStrategiesResponse,
  SignalsByStrategy,
  EnabledStrategy,
} from "@/types";

export const multiStrategyApi = {
  // 获取所有已启用策略
  getEnabledStrategies: async (): Promise<ApiResponse<EnabledStrategiesResponse>> => {
    return apiClient.get("/strategy/enabled");
  },

  // 启用一个策略
  enableStrategy: async (
    strategyId: string,
    presetName: string
  ): Promise<ApiResponse<EnabledStrategy>> => {
    return apiClient.post("/strategy/enable", {
      strategy_id: strategyId,
      preset_name: presetName,
    });
  },

  // 禁用一个策略
  disableStrategy: async (
    strategyId: string
  ): Promise<ApiResponse<{ auto_trade_paused: boolean }>> => {
    return apiClient.post("/strategy/disable", {
      strategy_id: strategyId,
    });
  },

  // 修改已启用策略的预设
  updateStrategyPreset: async (
    strategyId: string,
    presetName: string
  ): Promise<ApiResponse<EnabledStrategy>> => {
    return apiClient.post(`/strategy/${strategyId}/preset`, {
      preset_name: presetName,
    });
  },

  // 获取按策略分组的信号
  getSignalsByStrategy: async (): Promise<ApiResponse<SignalsByStrategy>> => {
    return apiClient.get("/signals/by-strategy");
  },

  // 设置自动交易跟随策略
  setAutoTradeStrategy: async (strategyId: string): Promise<ApiResponse> => {
    return apiClient.post("/strategy/auto-trade", {
      strategy_id: strategyId,
    });
  },

  // 获取当前自动交易跟随策略
  getAutoTradeStrategy: async (): Promise<
    ApiResponse<{ auto_trade_strategy: string | null }>
  > => {
    return apiClient.get("/strategy/auto-trade");
  },
};
