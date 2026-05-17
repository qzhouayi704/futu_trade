// 盘后优选 API 封装

const API_BASE = "/api/overnight-screen";

export interface OvernightCandidate {
  stock_code: string;
  stock_name: string;
  total_score: number;
  rank: number;
  verdict: string;
  category: string;
  scores: Record<string, number>;
  reasons: string[];
  key_metrics: Record<string, number>;
  excluded: boolean;
  exclude_reason: string;
  penalty_factor: number;
  penalty_reasons: string[];
  r5_candidate: boolean;
}

export interface ScreenStatus {
  running: boolean;
  progress: string;
  has_result: boolean;
  error: string | null;
  timestamp: string | null;
}

export interface ScreenResult {
  candidates: OvernightCandidate[];
  breakout_candidates?: any[];
  consolidation_candidates?: any[];
  timestamp: string;
  total: number;
}

export const overnightApi = {
  async trigger(): Promise<{ success: boolean; message: string }> {
    const res = await fetch(API_BASE, { method: "POST" });
    return res.json();
  },

  async getStatus(): Promise<ScreenStatus> {
    const res = await fetch(`${API_BASE}/status`);
    const json = await res.json();
    return json.data;
  },

  async getResult(): Promise<ScreenResult> {
    const res = await fetch(`${API_BASE}/result`);
    const json = await res.json();
    return json.data || { candidates: [], timestamp: "", total: 0 };
  },
};
