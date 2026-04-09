// 增强热度分析 API 客户端

import apiClient from "./client";
import type {
  MarketHeatData,
  CapitalFlowData,
  CapitalFlowBatchData,
  CapitalFlowHistoryData,
  BigOrderData,
  LeaderStocksData,
  OrderBookAnalysisData,
  TickerAnalysisData,
  CombinedAnalysisData,
  OrderBookResponse,
  PriceLevelDistributionData,
} from "@/types/enhanced-heat";

interface ApiResponse<T> {
  success: boolean;
  data: T;
  message: string;
}

/** 获取市场整体热度 */
export async function getMarketHeat(): Promise<ApiResponse<MarketHeatData>> {
  return apiClient.get("/enhanced-heat/market-heat");
}

/** 获取单只股票资金流向 */
export async function getCapitalFlow(
  stockCode: string
): Promise<ApiResponse<CapitalFlowData | null>> {
  return apiClient.get(`/enhanced-heat/capital-flow/${stockCode}`);
}

/** 批量获取资金流向 */
export async function getCapitalFlowBatch(
  codes: string[]
): Promise<ApiResponse<CapitalFlowBatchData>> {
  return apiClient.get("/enhanced-heat/capital-flow-batch", {
    params: { codes: codes.join(",") },
  });
}

/** 获取大单追踪数据 */
export async function getBigOrders(
  stockCode: string
): Promise<ApiResponse<BigOrderData | null>> {
  return apiClient.get(`/enhanced-heat/big-orders/${stockCode}`);
}

/** 获取历史每日资金流向 */
export async function getCapitalFlowHistory(
  stockCode: string,
  start?: string,
  end?: string
): Promise<ApiResponse<CapitalFlowHistoryData>> {
  return apiClient.get(`/enhanced-heat/capital-flow-history/${stockCode}`, {
    params: { start, end },
  });
}

/** 获取龙头股列表 */
export async function getLeaderStocks(
  maxTotal: number = 10
): Promise<ApiResponse<LeaderStocksData>> {
  return apiClient.get("/enhanced-heat/leader-stocks", {
    params: { max_total: maxTotal },
  });
}

/** 获取盘口深度分析（买卖十档 + 5维度涨跌动力） */
export async function getOrderBookAnalysis(
  stockCode: string
): Promise<ApiResponse<OrderBookAnalysisData | null>> {
  return apiClient.get(`/enhanced-heat/order-book/${stockCode}`);
}

/** 获取逐笔成交分析 */
export async function getTickerAnalysis(
  stockCode: string
): Promise<ApiResponse<TickerAnalysisData | null>> {
  return apiClient.get(`/enhanced-heat/ticker-analysis/${stockCode}`);
}

/** 获取综合多空分析（挂单 + 成交） */
export async function getCombinedAnalysis(
  stockCode: string
): Promise<ApiResponse<CombinedAnalysisData | null>> {
  return apiClient.get(`/enhanced-heat/combined-analysis/${stockCode}`);
}

/** 获取盘口10档原始数据（同 getOrderBookAnalysis，需从 data.order_book 提取） */
export const getOrderBook = getOrderBookAnalysis;

/** 获取价位成交分布 */
export async function getPriceDistribution(
  stockCode: string
): Promise<ApiResponse<PriceLevelDistributionData | null>> {
  return apiClient.get(`/enhanced-heat/price-distribution/${stockCode}`);
}
