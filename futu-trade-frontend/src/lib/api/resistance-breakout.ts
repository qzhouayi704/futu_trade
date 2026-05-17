// 阻力位突破扫描 API 封装

const API_BASE = "/api/resistance-breakout";

export interface ResistanceBreakoutCandidate {
  code: string;
  name: string;
  close: number;
  change_pct: number;
  // 日线突破
  daily_breakout_level: string;
  daily_resistance_price: number;
  daily_breakout_pct: number;
  // 日内突破
  intraday_breakout: boolean;
  intraday_level_type: string;
  intraday_level_label: string;
  intraday_resistance_price: number;
  intraday_resistance_strength: number;
  // 资金
  net_inflow_ratio: number;
  big_order_buy_ratio: number;
  capital_continuity_days: number;
  capital_score: number;
  main_net_inflow: number;
  // 量能
  turnover_rate: number;
  volume_ratio: number;
  // 综合
  score: number;
  signal_note: string;
}

export interface ScanStatus {
  running: boolean;
  progress: string;
  has_result: boolean;
  error: string | null;
  timestamp: string | null;
}

export interface ScanResult {
  candidates: ResistanceBreakoutCandidate[];
  timestamp: string;
  total: number;
}

export const resistanceBreakoutApi = {
  async trigger(): Promise<{ success: boolean; message: string }> {
    const res = await fetch(API_BASE, { method: "POST" });
    return res.json();
  },

  async getStatus(): Promise<ScanStatus> {
    const res = await fetch(`${API_BASE}/status`);
    const json = await res.json();
    return json.data;
  },

  async getResult(): Promise<ScanResult> {
    const res = await fetch(`${API_BASE}/result`);
    const json = await res.json();
    return json.data || { candidates: [], timestamp: "", total: 0 };
  },
};
