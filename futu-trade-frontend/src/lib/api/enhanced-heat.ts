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

export interface IntradayTimelinePoint {
  time: string;
  price: number;
  avg_price: number;
  volume: number;
  turnover: number;
}

/** 获取股票当天的分时折线数据 */
export async function getIntradayTimeline(
  stockCode: string
): Promise<ApiResponse<IntradayTimelinePoint[]>> {
  return apiClient.get(`/enhanced-heat/intraday-timeline/${stockCode}`);
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

// ==================== 日内支撑/阻力位 ====================

export interface IntradayPriceLevel {
  price: number;
  strength: number;
  type: string;       // volume_poc / big_order_buy / big_order_sell / order_book_bid / order_book_ask
  label: string;
  volume: number;
  reliability?: 'confirmed' | 'order_book_only';  // 价位可信度
}

export interface BrokerDetail {
  name: string;
  pos: number;        // 排队位置
  tag: '散户' | '机构' | '北水' | '未知';
}

export interface BrokerAnalysis {
  is_trap: boolean;
  trap_confidence: number;
  reason: string;
  top_buyers: string[];
  top_sellers: string[];
  buyer_details: BrokerDetail[];
  seller_details: BrokerDetail[];
  institutional_sell_count: number;
  retail_buy_count: number;
}

export interface IntradayLevelsData {
  stock_code: string;
  support_levels: IntradayPriceLevel[];
  resistance_levels: IntradayPriceLevel[];
  poc: { price: number; volume: number } | null;
  vwap: { price: number; deviation_pct: number } | null;
  current_price: number;
  updated_at: string;
  broker_analysis?: BrokerAnalysis;
}

/** 获取日内资金支撑/阻力位 */
export async function getIntradayLevels(
  stockCode: string
): Promise<ApiResponse<IntradayLevelsData | null>> {
  return apiClient.get(`/enhanced-heat/intraday-levels/${stockCode}`);
}

// ==================== 主力/散户资金流时间线 ====================

export interface CapitalFlowTimelinePoint {
  time: string;       // "HH:MM"
  main_in: number;    // 主力净流入（万元）= 超大单+大单
  retail_in: number;  // 散户净流入（万元）= 中单+小单
  total_in: number;   // 总净流入（万元）
  super_in?: number;  // 超大单净流入（万元）— 纯机构
  price?: number;     // 当时股价
  strength?: number;  // 大单强度 (-1 ~ +1)
  bs_ratio?: number;  // 大单买卖比
}

export interface FlowSummary {
  momentum_label: string;    // 加速流入/稳定流入/减速流入/冲高回落/加速流出/...
  momentum_change: number;   // 后半段相对前半段变化百分比
  signal: 'bullish' | 'bearish' | 'warning' | 'neutral';
  buy_sell_ratio: number;    // 总买入/总卖出
  cum_net: number;           // 累计净买入(万)
  recent_net: number;        // 最近5分钟净买入(万)
  first_half_net: number;
  second_half_net: number;
}

export interface CapitalFlowTimelineData {
  timeline: CapitalFlowTimelinePoint[];
  summary: FlowSummary | null;
}

/** 获取日内主力/散户资金流时间线（含动能摘要） */
export async function getCapitalFlowTimeline(
  stockCode: string
): Promise<ApiResponse<CapitalFlowTimelineData>> {
  const res = await apiClient.get(`/enhanced-heat/capital-flow-timeline/${stockCode}`);
  // 兼容旧格式（data 直接是数组）和新格式（data 是 {timeline, summary}）
  if (res.success && Array.isArray(res.data)) {
    return { ...res, data: { timeline: res.data, summary: null } };
  }
  return res;
}

/** CCASS 持仓变化数据 */
export interface CCASHoldingChange {
  participant_id: string;
  name: string;
  current_holding: number;
  prev_holding: number;
  change: number;
}

export interface CCASHoldingsData {
  stock_code: string;
  latest_date: string;
  compare_date: string;
  top_increases: CCASHoldingChange[];
  top_decreases: CCASHoldingChange[];
}

/** 获取 CCASS 持仓变化（首次请求需爬取 HKEX，可能需 30-60 秒） */
export async function getCCASHoldings(
  stockCode: string
): Promise<ApiResponse<CCASHoldingsData>> {
  return apiClient.get(`/enhanced-heat/ccass-holdings/${stockCode}`, {
    timeout: 65000, // HKEX 爬取较慢，首次需要 30-60 秒
  });
}
