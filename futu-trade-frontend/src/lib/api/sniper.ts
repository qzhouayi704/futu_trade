// Sniper API — 盘中狙击手相关接口

import apiClient from "./client";
import type { ApiResponse } from "@/types";

export const sniperApi = {
  /** 获取今日所有信号 */
  getSignals: (): Promise<ApiResponse> => apiClient.get("/sniper/signals"),

  /** 获取最近N分钟信号 */
  getRecentSignals: (minutes = 30): Promise<ApiResponse> =>
    apiClient.get(`/sniper/signals/recent?minutes=${minutes}`),

  /** 获取TOP排行榜 */
  getRanking: (): Promise<ApiResponse> => apiClient.get("/sniper/ranking"),

  /** 批量盘口判定(追高/洗盘)，codes 逗号分隔 */
  getTapeVerdicts: (codes: string): Promise<ApiResponse> =>
    apiClient.get(`/sniper/tape-verdicts?codes=${encodeURIComponent(codes)}`),

  /** 获取Sniper止盈追踪状态 */
  getTrailingStatus: (): Promise<ApiResponse> => apiClient.get("/sniper/trailing-status"),

  /** 获取信号处理流水 */
  getSignalPipeline: (limit = 50, date = ""): Promise<ApiResponse> =>
    apiClient.get(`/sniper/signal-pipeline?limit=${limit}&date=${date}`),

  /** 获取模拟交易记录 */
  getSimulatedTrades: (limit = 30): Promise<ApiResponse> =>
    apiClient.get(`/sniper/simulated-trades?limit=${limit}`),

  /** 获取每日模拟交易统计 */
  getSimulatedTradesDaily: (date = "", limit = 100): Promise<ApiResponse> =>
    apiClient.get(`/sniper/simulated-trades/daily?date=${date}&limit=${limit}`),
};

