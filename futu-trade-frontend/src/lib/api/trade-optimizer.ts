// 交易优化 API 客户端

import apiClient from "./client";

interface ApiResponse<T> {
  success: boolean;
  data: T;
  message?: string;
}

// ==================== 类型定义 ====================

export interface ScoreDetail {
  dimension: string;
  value: number | null;
  score: number;
  max: number;
  note?: string;
}

export interface ScoringResult {
  stock_code: string;
  stock_name: string;
  total_score: number;
  passed: boolean;
  veto_reason: string;
  details: ScoreDetail[];
  timestamp: string;
}

export interface ScoringStatus {
  total_scored: number;
  candidates: number;
  candidate_list: ScoringResult[];
  all_scores: ScoringResult[];
}

export interface PhaseStatus {
  phase: string;
  can_buy: boolean;
  can_sell: boolean;
  buy_strategy: string;
  note: string;
  rotation_count: number;
  max_rotations: number;
}

export interface GuardStatus {
  date: string;
  trade_count: number;
  max_trades: number;
  buy_counts: Record<string, number>;
  daily_pnl: number;
  circuit_broken: boolean;
  current_phase: string;
}

export interface CanBuyCheck {
  stock_code: string;
  all_passed: boolean;
  score: number;
  checks: Array<{ name: string; passed: boolean; reason: string }>;
}

export interface OverviewData {
  timestamp: string;
  phase?: PhaseStatus;
  guard?: GuardStatus;
  scoring?: {
    total_scored: number;
    candidates: number;
    top3: Array<{ code: string; name: string; score: number }>;
  };
  positions?: { active: number };
  rotation?: { count: number; max: number };
}

// ==================== API 函数 ====================

/** 获取评分系统状态 */
export async function getScoringStatus(): Promise<ApiResponse<ScoringStatus>> {
  return apiClient.get("/trade-optimizer/scoring/status");
}

/** 获取单只标的评分 */
export async function getStockScore(stockCode: string): Promise<ApiResponse<ScoringResult>> {
  return apiClient.get(`/trade-optimizer/scoring/stock/${stockCode}`);
}

/** 获取当前交易阶段 */
export async function getCurrentPhase(): Promise<ApiResponse<PhaseStatus>> {
  return apiClient.get("/trade-optimizer/phase/current");
}

/** 获取频率管控状态 */
export async function getGuardStatus(): Promise<ApiResponse<GuardStatus>> {
  return apiClient.get("/trade-optimizer/guard/status");
}

/** 检查能否买入 */
export async function checkCanBuy(stockCode: string): Promise<ApiResponse<CanBuyCheck>> {
  return apiClient.get(`/trade-optimizer/guard/can-buy/${stockCode}`);
}

/** 获取系统总览 */
export async function getOptimizerOverview(): Promise<ApiResponse<OverviewData>> {
  return apiClient.get("/trade-optimizer/overview");
}

/** 手动触发盘前评分 */
export async function runPreMarketScoring(): Promise<ApiResponse<{ total: number; passed: number; candidates: ScoringResult[] }>> {
  return apiClient.post("/trade-optimizer/scoring/run");
}

/** 每日重置 */
export async function dailyReset(): Promise<ApiResponse<Array<{ name: string; success: boolean; error?: string }>>> {
  return apiClient.post("/trade-optimizer/daily-reset");
}
