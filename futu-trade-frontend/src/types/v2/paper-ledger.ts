export interface PaperLedgerOrder {
  plan_id: string;
  stock_code: string;
  approved_at: string;
  status: string;
  quantity: number;
  bought: number;
  sold: number;
  held: number;
  entry_remaining: number;
  entry_min: string;
  entry_limit: string;
  stop_price: string;
  valid_until: string;
  exit_at: string;
  entry_end_reason: string | null;
  exit_reason: string | null;
  closed_net_pnl: string | null;
  average_buy_price?: string | null;
  position_reason?: string | null;
  position_evaluated_at?: string | null;
  exit_triggered_at?: string | null;
}

export interface PaperLedgerSnapshot {
  reported_at: string;
  as_of: string | null;
  account_id: string;
  experiment_id: string;
  strategy_id: string;
  strategy_version: string;
  exit_policy?: "RESEARCH_ATR" | "PRODUCTION_RULES";
  stale_analysis_codes?: string[];
  stock_codes: string[];
  run_record_status: string;
  run_error_code: string | null;
  cash: string;
  reserved_cash: string;
  marked_equity: string;
  closed_order_net_pnl: string;
  closed_order_count: number;
  fees: string;
  stale_position_codes: string[];
  order_count: number;
  orders: PaperLedgerOrder[];
  fill_count: number;
  recent_fills: Array<{
    fill_id: string; stock_code: string; side: string; quantity: number;
    price: string; fee: string; exchange_time: string;
  }>;
  recent_signals: Array<{
    event_id: string; stock_code: string; processed_at: string; reason: string;
  }>;
}

export interface PaperLedgerView {
  status: "DISABLED" | "NOT_INITIALIZED" | "RUNNING" | "STOPPED" | "ERROR";
  execution_enabled: false;
  runtime: {
    running: boolean; account_id: string; experiment_id: string;
    queued: number; processed: number; dropped: number; queue_size: number;
    active_codes: string[]; plans: number; fills: number;
    cash: string | null; equity: string | null; stale_position_codes: string[];
    as_of: string | null; last_result: string | null; error: string | null;
  } | null;
  ledger: PaperLedgerSnapshot | null;
}
