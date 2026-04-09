// 系统 API

import apiClient from "./client";
import type { ApiResponse } from "@/types";

export const systemApi = {
  // 获取系统状态
  getStatus: async (): Promise<
    ApiResponse<{
      is_running: boolean;
      futu_connected: boolean;
      monitor_status: string;
    }>
  > => {
    return apiClient.get("/system/status");
  },

  // 获取详细系统信息
  getSystemInfo: async (types?: string[]): Promise<ApiResponse<any>> => {
    return apiClient.get("/system/info", {
      params: types ? { types: types.join(",") } : undefined,
    });
  },

  // 系统诊断
  diagnose: async (): Promise<ApiResponse<any>> => {
    return apiClient.get("/system/diagnosis");
  },

  // 启动监控
  startMonitor: async (): Promise<ApiResponse> => {
    return apiClient.post("/monitor/start");
  },

  // 使用指定策略启动监控
  startWithStrategy: async (params?: {
    strategy_id?: string;
    preset_name?: string;
  }): Promise<
    ApiResponse<{
      strategy_id: string;
      strategy_name: string;
      preset_name: string;
      subscribed_count: number;
    }>
  > => {
    return apiClient.post("/monitor/start-with-strategy", params || {});
  },

  // 停止监控
  stopMonitor: async (): Promise<ApiResponse> => {
    return apiClient.post("/monitor/stop");
  },

  // 获取监控状态
  getMonitorStatus: async (): Promise<
    ApiResponse<{
      is_running: boolean;
      start_time?: string;
    }>
  > => {
    return apiClient.get("/monitor/status");
  },

  // 获取监控健康状态
  getMonitorHealth: async (): Promise<
    ApiResponse<{
      status: {
        is_running: boolean;
        futu_api_available: boolean;
        monitor_thread_alive: boolean;
      };
      stock_pool: {
        total_count: number;
        has_data: boolean;
      };
      subscription: {
        subscribed_count: number;
        has_subscription: boolean;
      };
      last_update: string | null;
    }>
  > => {
    return apiClient.get("/monitor/health");
  },
};
