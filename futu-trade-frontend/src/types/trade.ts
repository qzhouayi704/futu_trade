// 交易相关类型定义

export interface TradeSignal {
  id: number;
  stock_id: number;
  stock_code: string;
  stock_name: string;
  signal_type: "buy" | "sell";
  signal_price: number;
  target_price: number | null;
  stop_loss_price: number | null;
  condition_text: string;
  strategy_id: string;
  strategy_name: string;
  is_executed: boolean;
  executed_time: string | null;
  created_at: string;
}

export interface Position {
  id?: number;
  stock_code: string;
  stock_name: string;
  qty: number;
  quantity?: number; // 兼容字段
  can_sell_qty: number;
  cost_price: number;
  current_price?: number; // 当前价格
  market_value: number;
  pl_val: number;
  pl_ratio: number;
  today_pl_val: number;
}

export interface TradeRecord {
  id: number;
  stock_code: string;
  stock_name: string;
  trade_type: "buy" | "sell";
  trade_price: number;
  quantity: number;
  trade_time: string;
  status: string;
}

export interface OrderForm {
  stock_code: string;
  trade_type: "buy" | "sell";
  price?: number;
  quantity: number;
  signal_id?: number;
}

// ==================== 分仓止盈类型 ====================

export interface PositionLot {
  deal_id: string;
  stock_code: string;
  buy_price: number;
  quantity: number;
  remaining_qty: number;
  deal_time: string;
  current_profit_pct: number;
  trigger_price: number;
}

export interface TakeProfitTask {
  id: number;
  stock_code: string;
  stock_name: string;
  take_profit_pct: number;
  status: "ACTIVE" | "COMPLETED" | "CANCELLED";
  total_lots: number;
  sold_lots: number;
  created_at: string;
  updated_at: string;
  executions?: TakeProfitExecution[];
}

export interface TakeProfitExecution {
  id: number;
  task_id: number;
  stock_code: string;
  lot_buy_price: number;
  lot_quantity: number;
  trigger_price: number;
  sell_price: number | null;
  profit_amount: number | null;
  status: "PENDING" | "TRIGGERED" | "EXECUTED" | "FAILED" | "CANCELLED";
  triggered_at: string | null;
  executed_at: string | null;
  error_msg: string | null;
}

// ==================== 持仓订单历史 + 单笔止盈类型 ====================

export interface OrderRecord extends PositionLot {
  take_profit_status: 'PENDING' | 'TRIGGERED' | 'EXECUTED' | 'FAILED' | 'CANCELLED' | null;
  take_profit_price: number | null;
  take_profit_pct: number | null;
  execution_id: number | null;
}

export interface CreateLotTakeProfitRequest {
  stock_code: string;
  deal_id: string;
  buy_price: number;
  quantity: number;
  take_profit_pct: number;
  take_profit_price: number;
}

export interface PositionCapitalFlow {
  stock_code: string;
  stock_name: string;
  qty: number;
  cost_price: number;
  nominal_price: number;
  market_val: number;
  pl_val: number;
  pl_ratio: number;
  main_net_inflow: number;
  net_inflow_ratio: number;
  capital_score: number;
  big_order_buy_ratio: number;
  super_large_inflow: number;
  super_large_outflow: number;
  large_inflow: number;
  large_outflow: number;
  medium_inflow: number;
  medium_outflow: number;
  small_inflow: number;
  small_outflow: number;
  inflow_change: number;
  has_flow_data: boolean;
  // 逐笔 BSR 字段
  ticker_bsr: number;
  ticker_power: number;
  ticker_buy_turnover: number;
  ticker_sell_turnover: number;
  ticker_count: number;
  has_ticker_data: boolean;
}

