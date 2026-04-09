// 增强热度分析相关类型定义

/** 市场热度数据 */
export interface MarketHeatData {
  market_heat: number;
  sentiment: string;
  recommended_position_ratio: number;
  hot_plates: HotPlateItem[];
  quote_coverage?: number;  // 报价覆盖率 (0-1)
}

/** 热门板块项（扩展实时数据） */
export interface HotPlateItem {
  plate_code: string;
  plate_name: string;
  stock_count: number;
  avg_change_pct: number;    // 板块平均涨幅
  up_ratio: number;           // 涨跌比
  hot_stock_count: number;    // 大涨股数量
  leading_stock_name: string; // 领涨股名称
  heat_score: number;         // 板块热度分
}

/** 资金流向数据 */
export interface CapitalFlowData {
  stock_code: string;
  timestamp: string;
  main_net_inflow: number;
  super_large_inflow: number;
  large_inflow: number;
  medium_inflow: number;
  small_inflow: number;
  super_large_outflow: number;
  large_outflow: number;
  medium_outflow: number;
  small_outflow: number;
  net_inflow_ratio: number;
  big_order_buy_ratio: number;
  capital_score: number;
}

/** 批量资金流向响应 */
export interface CapitalFlowBatchData {
  capital_flows: Record<string, CapitalFlowData>;
  total: number;
  requested: number;
}

/** 大单追踪数据 */
export interface BigOrderData {
  stock_code: string;
  timestamp: string;
  big_buy_count: number;
  big_sell_count: number;
  big_buy_amount: number;
  big_sell_amount: number;
  buy_sell_ratio: number;
  order_strength: number;
}

/** 龙头股候选（扩展字段） */
export interface LeaderStockItem {
  stock_code: string;
  stock_name: string;
  market: string;
  plate_code: string;
  plate_name: string;
  last_price: number;
  change_pct: number;
  volume: number;
  turnover: number;
  price_position: number;
  heat_score: number;
  is_leader: boolean;
  leader_rank: number;
  signal_strength: number;
  timestamp: string;
  leader_score: number;            // 龙头评分
  consecutive_strong_days: number; // 连续强势天数
  market_cap: number;              // 市值
}

/** 三级筛选漏斗统计 */
export interface ScreeningStats {
  total_count: number;
  level1_count: number;
  level2_count: number;
  level3_count: number;
  quoted_count?: number;  // 有报价数据的股票数量
}

/** 龙头股列表响应 */
export interface LeaderStocksData {
  leaders: LeaderStockItem[];
  total: number;
  screening_stats?: ScreeningStats;
  data_ready?: boolean;
}

/** 历史资金流向单日数据 */
export interface CapitalFlowHistoryItem {
  date: string;
  net_inflow: number;
  main_net_inflow: number;
  super_large_net_inflow: number;
  large_net_inflow: number;
  medium_net_inflow: number;
  small_net_inflow: number;
}

/** 历史资金流向响应 */
export interface CapitalFlowHistoryData {
  history: CapitalFlowHistoryItem[];
  total: number;
}

// ==================== 盘口深度分析 ====================

/** 盘口单档数据 */
export interface OrderBookLevel {
  price: number;
  volume: number;
  order_count: number;
}

/** 盘口原始数据 */
export interface OrderBookRaw {
  bid_levels: OrderBookLevel[];
  ask_levels: OrderBookLevel[];
  bid_total_volume: number;
  ask_total_volume: number;
  imbalance: number;
  spread: number;
  spread_pct: number;
  support: { price: number; volume: number } | null;
  resistance: { price: number; volume: number } | null;
}

/** 分析维度信号 */
export type SignalType = 'bullish' | 'slightly_bullish' | 'neutral' | 'slightly_bearish' | 'bearish';

export interface DimensionSignal {
  name: string;
  signal: SignalType;
  score: number;
  description: string;
  details: Record<string, number | string | boolean>;
}

/** 盘口深度分析结果 */
export interface OrderBookAnalysisData {
  stock_code: string;
  order_book: OrderBookRaw;
  dimensions: DimensionSignal[];
  total_score: number;
  signal: SignalType;
  label: string;
  summary: string;
}

// ==================== 成交分析 ====================

/** 成交密集区 */
export interface VolumeCluster {
  price: number;
  volume: number;
  turnover: number;
  buy_pct: number;
  sell_pct: number;
  neutral_pct: number;
  type: 'support' | 'resistance' | 'current';
}

/** 买卖比分时走势数据点 */
export interface BuySellTimelinePoint {
  time: string;
  buy_turnover: number;
  sell_turnover: number;
  ratio: number;
  trade_count: number;
  cumulative_net: number;
}

/** 成交分析结果 */
export interface TickerAnalysisData {
  stock_code: string;
  dimensions: DimensionSignal[];
  total_score: number;
  signal: SignalType;
  label: string;
  summary: string;
}

/** 综合分析结果 */
export interface CombinedAnalysisData {
  stock_code: string;
  order_book_dimensions: DimensionSignal[];
  ticker_dimensions: DimensionSignal[];
  order_book_score: number;
  ticker_score: number;
  combined_score: number;
  signal: SignalType;
  label: string;
  summary: string;
  has_contradiction: boolean;
  ticker_available: boolean;
}

/** 盘口10档 API 响应 */
export interface OrderBookResponse {
  stock_code: string;
  bid_levels: OrderBookLevel[];
  ask_levels: OrderBookLevel[];
  bid_total_volume: number;
  ask_total_volume: number;
  imbalance: number;
  spread: number;
  spread_pct: number;
  support: { price: number; volume: number } | null;
  resistance: { price: number; volume: number } | null;
}

// ==================== 价位成交分布 ====================

/** 单个价位数据 */
export interface PriceLevelItem {
  price: number;
  total_volume: number;
  total_turnover: number;
  trade_count: number;
  buy_volume: number;
  sell_volume: number;
  neutral_volume: number;
}

/** 价位成交分布数据 */
export interface PriceLevelDistributionData {
  stock_code: string;
  levels: PriceLevelItem[];
  current_price: number;
  total_volume: number;
  total_turnover: number;
  level_count: number;
}
