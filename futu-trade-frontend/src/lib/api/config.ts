// 配置 API

import apiClient from "./client";
import type { ApiResponse } from "@/types";

export interface SystemConfig {
  futu_host: string;
  futu_port: number;
  database_path: string;
  update_interval: number;
  auto_trade: boolean;
  max_stocks_monitor: number;
  max_subscribe_count: number;
  realtime_hot_filter: {
    enable: boolean;
    min_turnover_rate: number;
    min_volume: number;
    top_n: number;
  };
  [key: string]: any;
}

export const configApi = {
  // 获取当前配置
  getConfig: async (): Promise<ApiResponse<SystemConfig>> => {
    return apiClient.get("/config");
  },

  // 更新配置
  updateConfig: async (config: Partial<SystemConfig>): Promise<ApiResponse> => {
    return apiClient.put("/config", config);
  },

  // 重置配置
  resetConfig: async (): Promise<ApiResponse> => {
    return apiClient.post("/config/reset");
  },
};
