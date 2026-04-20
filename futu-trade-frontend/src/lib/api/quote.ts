// 行情报价 API

import apiClient from "./client";
import type { ApiResponse, QuoteData, TradingCondition } from "@/types";

export const quoteApi = {
  // 获取实时报价
  getQuotes: async (stockCodes?: string[]): Promise<ApiResponse<QuoteData[]>> => {
    return apiClient.get("/quotes", {
      params: stockCodes ? { codes: stockCodes.join(",") } : undefined,
    });
  },

  // 获取交易条件
  getTradingConditions: async (): Promise<ApiResponse<TradingCondition[]>> => {
    return apiClient.get("/quotes/conditions");
  },

  // 获取交易信号
  getTradeSignals: async (): Promise<ApiResponse<unknown[]>> => {
    return apiClient.get("/quotes/trade-signals");
  },

  // 获取预警信息
  getAlerts: async (): Promise<ApiResponse<unknown[]>> => {
    return apiClient.get("/quotes/alerts");
  },

  // 获取K线配额信息
  getKlineQuota: async (): Promise<
    ApiResponse<{
      used: number;
      remaining: number;
      total: number;
      usage_rate: number;
    }>
  > => {
    return apiClient.get("/quotes/quota");
  },

  // 获取订阅状态
  getSubscriptionStatus: async (): Promise<ApiResponse<unknown>> => {
    return apiClient.get("/quotes/subscription-status");
  },

  // 获取热门股票
  getHotStocks: async (params?: {
    limit?: number;
    market?: string;
  }): Promise<ApiResponse<unknown[]>> => {
    return apiClient.get("/quotes/hot-stocks", { params });
  },

  // 获取K线数据
  getKlineData: async (
    stockCode: string,
    period: "day" | "week" | "month"
  ): Promise<ApiResponse<unknown[]>> => {
    return apiClient.get(`/quotes/kline/${stockCode}`, {
      params: { period },
    });
  },
};
