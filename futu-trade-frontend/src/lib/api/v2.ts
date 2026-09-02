import apiClient from "./client";
import type { ApiResponse } from "@/types";

export interface V2Candidate {
  stock_code: string;
  stock_name: string;
  status: string;
  version: number;
  confirmed_price: number | null;
  peak_price: number | null;
  updated_at: string;
  reason_code: string;
  score: number | null;
  portfolio_score?: number | null;
  quality: string | null;
  strategy_sources: string[];
  consensus_count: number;
  alert_eligible: boolean;
  strategy_nominations?: Array<{
    strategy_id: string;
    eligible: boolean;
    stage: "REJECTED" | "WATCH" | "CONFIRMED";
    score: number;
    reason_codes: string[];
  }>;
  quote?: { last_price?: number; prev_close?: number };
  market_context?: { market_breadth?: number; sector_breadth?: number | null; market_regime?: string };
  price_position?: { daily_percentile?: number; structure?: string; distance_to_ma20?: number };
  capital_memory?: {
    state: string;
    score: number;
    day_main_net: number;
    decayed_main_net: number;
    recent_15m_main_net: number;
    decayed_buy_events: number;
    decayed_sell_events: number;
    recent_15m_buy_events: number;
    recent_15m_sell_events: number;
    quality: string;
  } | null;
  capital_windows: Array<{
    window_seconds: number;
    main_net: number;
    independent_buy_events: number;
    independent_sell_events: number;
    buy_sell_ratio: number | null;
  }>;
}

export interface V2CandidateHistoryItem {
  stock_code: string;
  stock_name: string;
  first_seen_at: string;
  last_seen_at: string;
  event_count: number;
  max_stage: string;
  latest_score: number | null;
  strategy_version_count: number;
  latest_event_type: string;
  latest_status: string;
  latest_reason_code: string;
  latest_strategy_version: string;
  quote?: { last_price?: number; prev_close?: number };
  capital_memory?: {
    state?: string;
    day_main_net?: number;
    decayed_main_net?: number;
  } | null;
}

export interface V2CandidateTimelineEvent {
  event_id: string;
  event_type: string;
  stock_code: string;
  exchange_time: string;
  old_state: string | null;
  new_state: string | null;
  reason_code: string;
  strategy_version: string;
  score: number | null;
  capital_state: string | null;
  day_main_net: number | null;
}

export interface V2CandidateHistory {
  items: V2CandidateHistoryItem[];
  total: number;
  page: number;
  page_size: number;
  trade_date: string;
  scope: "entered" | "all";
}

export interface V2Position {
  stock_code: string;
  stock_name: string;
  status: string;
  opened_at: string;
  cost_price: number;
  peak_price: number;
  trough_price: number;
  mfe_pct: number;
  mae_pct: number;
  stalled_since: string | null;
  updated_at: string;
  reason_code: string;
  last_action: string | null;
  position?: { current_price?: number; current_return_pct?: number; quantity?: number };
  efficiency?: {
    score?: number;
    current_return_pct?: number;
    drawdown_from_peak_pct?: number;
    flow_drawdown_ratio?: number;
    slope_15m_pct?: number | null;
    minutes_since_high?: number;
  };
  rotation?: {
    buy_stock_code?: string;
    candidate_score?: number;
    held_efficiency_score?: number;
    net_advantage_score?: number;
    estimated_cost_pct?: number;
  } | null;
}

export interface V2Decision {
  event_id: string;
  event_type: string;
  stock_code: string;
  exchange_time: string;
  old_state: string | null;
  new_state: string | null;
  reason_code: string;
  strategy_version: string;
}

export interface V2Outcome {
  event_id: string;
  stock_code: string;
  stock_name: string;
  event_type: string;
  signal_time: string;
  signal_price: number;
  mfe_pct: number | null;
  mae_pct: number | null;
  close_return_pct: number | null;
  next_day_return_pct: number | null;
  reached_1_5: boolean;
  reached_3: boolean;
  reached_5: boolean;
  time_to_1_5_seconds: number | null;
  time_to_3_seconds: number | null;
  time_to_5_seconds: number | null;
  hold_control_return_pct: number | null;
  rotation_return_pct: number | null;
}

interface DistributionMetric {
  count: number;
  percentiles: Record<string, number | null>;
  max: number | null;
  min: number | null;
  mean: number | null;
  histogram?: Array<{ label: string; count: number; ratio: number }>;
}

export interface V2Distribution {
  sample_count: number;
  mfe: DistributionMetric;
  mae: DistributionMetric;
  close_return: DistributionMetric;
  rotation_advantage: DistributionMetric;
  milestones: {
    reached_1_5_ratio: number;
    reached_3_ratio: number;
    reached_5_ratio: number;
  };
  items: V2Outcome[];
}

export interface V2CohortMetric {
  key?: string;
  sample_count: number;
  completed_count: number;
  reached_1_5_ratio: number;
  reached_3_ratio: number;
  reached_5_ratio: number;
  mfe: DistributionMetric;
  mae: DistributionMetric;
  close_return: DistributionMetric;
  median_time_to_1_5_seconds: number | null;
}

export interface V2ShadowAcceptance {
  target_days: number;
  observed_days: number;
  ready: boolean;
  date_range: { start: string | null; end: string | null };
  sample_count: number;
  entry_summary: V2CohortMetric;
  first_inflow_control: V2CohortMetric;
  rotation_summary: V2CohortMetric & {
    comparable_count: number;
    advantage: DistributionMetric;
    rotation_win_ratio: number;
  };
  cohorts: {
    market_regime: V2CohortMetric[];
    confirmation_window: V2CohortMetric[];
    inflow_frequency: V2CohortMetric[];
    outflow_context: V2CohortMetric[];
    signal_stage: V2CohortMetric[];
  };
  daily: Array<{
    trade_date: string;
    entry: V2CohortMetric;
    first_inflow: V2CohortMetric;
    rotation: V2ShadowAcceptance["rotation_summary"];
  }>;
  warnings: string[];
}

export interface V2Cockpit {
  mode: string;
  strategy_version: string | null;
  summary: {
    confirmed_candidates: number;
    open_positions: number;
    actionable_positions: number;
    evaluated_signals: number;
    reached_5_ratio: number;
  };
  candidates: V2Candidate[];
  positions: V2Position[];
  decisions: V2Decision[];
}

export interface V2Health {
  status: string;
  mode: string;
  event_queue: { size: number; capacity: number; dropped: number };
  tasks: Array<{ name?: string; status?: string; failure?: string | null }>;
  execution_enabled: boolean;
}

async function getData<T>(path: string): Promise<T> {
  const response = await apiClient.get<never, ApiResponse<T>>(path);
  if (!response.success || response.data === undefined) {
    throw new Error(response.message || "V2 数据读取失败");
  }
  return response.data;
}

export const v2Api = {
  cockpit: () => getData<V2Cockpit>("/v2/cockpit"),
  candidates: () => getData<{ items: V2Candidate[]; count: number }>("/v2/candidates"),
  candidateHistory: (params: {
    scope: "entered" | "all";
    page: number;
    pageSize?: number;
    search?: string;
    status?: string;
  }) => {
    const query = new URLSearchParams({
      scope: params.scope,
      page: String(params.page),
      page_size: String(params.pageSize || 50),
    });
    if (params.search) query.set("search", params.search);
    if (params.status) query.set("status", params.status);
    return getData<V2CandidateHistory>(`/v2/candidates/history?${query}`);
  },
  candidateTimeline: (stockCode: string, tradeDate: string) =>
    getData<{ items: V2CandidateTimelineEvent[]; count: number }>(
      `/v2/candidates/${encodeURIComponent(stockCode)}/timeline?trade_date=${tradeDate}`,
    ),
  positions: () => getData<{ items: V2Position[]; count: number }>("/v2/positions"),
  decisions: () => getData<{ items: V2Decision[]; count: number }>("/v2/decisions?limit=200"),
  distribution: () => getData<V2Distribution>("/v2/outcomes/distribution"),
  shadowAcceptance: () => getData<V2ShadowAcceptance>("/v2/outcomes/shadow-acceptance?days=10"),
  health: () => getData<V2Health>("/v2/system/health"),
};
