// 股票和板块相关类型定义

export interface Plate {
  id: number;
  plate_code: string;
  plate_name: string;
  market: string;
  is_target: boolean;
  is_enabled: boolean;
  priority: number;
  created_at: string;
  stock_count?: number;
}

export interface Stock {
  id: number;
  code: string;
  name: string;
  market: string;
  is_manual: boolean;
  stock_priority: number;
  heat_score: number | null;
  created_at: string;
  plates?: Plate[];
}

export interface StockPool {
  plates: Plate[];
  stocks: Stock[];
  initialized: boolean;
}

export interface PlateDetail {
  plate: Plate;
  stocks: Stock[];
  total: number;
}

// 板块股票列表项（含内嵌报价数据）
export interface PlateStock {
  id: number;
  code: string;
  name: string;
  market: string;
  last_price?: number;
  change_percent?: number;
  volume?: number;
  turnover_rate?: number;
  is_realtime?: boolean;
}

export interface HotStock extends Stock {
  last_price: number;
  change_rate: number;
  turnover_rate: number;
  volume: number;
  heat_score: number;
}

// 后端返回的热门股票数据格式
export interface BackendHotStock {
  code?: string;
  stock_code?: string;
  name?: string;
  stock_name?: string;
  market: string;
  cur_price?: number;
  current_price?: number;
  change_rate?: number;
  change_pct?: number;
  heat_score?: number;
  turnover_rate?: number;
  volume?: number;
}

// 后端返回的持仓数据格式
export interface BackendPosition {
  stock_code: string;
  stock_name: string;
  qty: number;
  cost_price: number;
  nominal_price: number;
  market_val: number;
  pl_val: number;
  pl_ratio: number;
  can_sell_qty?: number;
  today_pl_val?: number;
}

// 前端显示的持仓数据格式
export interface PositionDisplay {
  stock_code: string;
  stock_name: string;
  quantity: number;
  avg_price: number;
  current_price: number;
  market_value: number;
  profit_loss: number;
  profit_loss_pct: number;
}

// 前端显示的热门股票格式
export interface HotStockDisplay {
  stock_code: string;
  stock_name: string;
  market: string;
  current_price: number;
  change_pct: number;
  heat_score: number;
  turnover_rate: number;
  volume: number;
}

// 板块强度数据
export interface PlateStrength {
  plate_code: string;
  plate_name: string;
  market?: string;
  strength_score: number;
  leader_count: number;
  up_stock_ratio?: number;
  avg_change_pct?: number;
  avg_change_rate?: number;
  total_stocks?: number;
  total_volume?: number;
}

// 系统状态
export interface SystemStatus {
  is_running: boolean;
  market?: string;
  futu_connected?: boolean;
  monitor_status?: string;
  strategy_id?: number;
  strategy_name?: string;
  start_time?: string;
  subscribed_count?: number;
  stock_pool_count?: number;
}

// 统计数据
export interface Stats {
  stockPoolCount: number;
  subscribedCount: number;
  hotStockCount: number;
  positionCount: number;
}

/** 成交分析摘要 */
export interface TickerSummary {
  score: number;           // 综合评分 -100~100
  signal: string;          // bullish/slightly_bullish/neutral/slightly_bearish/bearish
  label: string;           // 中文标签
  buy_sell_ratio: number;  // 主动买卖力量比
  net_turnover: number;    // 主动买卖净额
  bias: string;            // strong_bullish/bullish/bearish/neutral
  bias_label: string;      // 强买/偏多/偏空/中性
  big_order_pct: number;   // 大单成交占比（%）
}

// 高换手率股票数据
export interface HighTurnoverStock {
  rank: number;
  code: string;
  name: string;
  market: string;
  turnover_rate: number;
  change_rate: number;
  last_price: number;
  volume: number;
  turnover: number;
  volume_ratio: number;
  amplitude: number;
  plates: { plate_code: string; plate_name: string }[];
  ticker_summary: TickerSummary | null;
  is_position?: boolean;
}

// 高换手率 API 响应
export interface HighTurnoverResponse {
  stocks: HighTurnoverStock[];
  total: number;
  update_time: string;
}

export interface CapitalFlowSummary {
  main_net_inflow: number;
  big_order_buy_ratio: number;
  capital_score: number;
}

// Top Hot API 响应数据
export interface TopHotResponse {
  stocks: TopHotStock[];
  market_info: Record<string, unknown>;
  active_markets: string[];
  filter_config: Record<string, unknown>;
  data_ready_status: DataReadyStatus;
  cache_timestamp: string;
  cache_duration: number;
}

export interface TopHotStock {
  id: number;
  code: string;
  name: string;
  market: string;
  heat_score: number;
  cur_price: number;
  last_price: number;
  change_rate: number;
  volume: number;
  turnover: number;
  turnover_rate: number;
  amplitude: number;
  high_price: number;
  low_price: number;
  open_price: number;
  prev_close_price: number;
  is_position: boolean;
  has_condition: boolean;
  condition: Record<string, unknown> | null;
  capital_flow_summary?: CapitalFlowSummary | null;
  capital_signal?: 'bullish' | 'bearish' | 'neutral';
}

export interface DataReadyStatus {
  data_ready: boolean;
  cached_count: number;
  expected_count: number;
  ready_percent: number;
}
