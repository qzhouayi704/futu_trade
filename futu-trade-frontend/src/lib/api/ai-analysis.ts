// AI 股票分析 API 客户端

import apiClient from "./client";

/** AI 分析结果类型 */
export interface AIAnalysisResult {
  stock_code: string;
  stock_name: string;
  action: "STRONG_BUY" | "BUY" | "HOLD" | "REDUCE" | "SELL" | "STRONG_SELL";
  confidence: number;
  reasoning: string;
  key_factors: string[];
  risk_warning: string | null;
  target_price: number | null;
  stop_loss_price: number | null;
  score_assessment: string;
  time_horizon: string;
  analyzed_at: string;
}

/** AI 分析响应 */
export interface AIAnalysisResponse {
  success: boolean;
  data?: AIAnalysisResult;
  message?: string;
}

/**
 * 对单只股票执行 AI 分析
 */
export async function analyzeStockAI(stockCode: string): Promise<AIAnalysisResponse> {
  const res = await apiClient.post(`/ai-analysis/analyze?stock_code=${encodeURIComponent(stockCode)}`);
  return res as unknown as AIAnalysisResponse;
}

/**
 * 清除 AI 分析缓存
 */
export async function clearAICache(stockCode?: string): Promise<void> {
  const params = stockCode ? `?stock_code=${encodeURIComponent(stockCode)}` : "";
  await apiClient.delete(`/ai-analysis/cache${params}`);
}

/** Action 的中文映射 */
export const ACTION_LABELS: Record<string, { label: string; color: string; bg: string; emoji: string }> = {
  STRONG_BUY: { label: "强烈买入", color: "text-red-700", bg: "bg-red-100", emoji: "🔥" },
  BUY: { label: "买入", color: "text-red-600", bg: "bg-red-50", emoji: "📈" },
  HOLD: { label: "持有", color: "text-yellow-700", bg: "bg-yellow-100", emoji: "⏳" },
  REDUCE: { label: "减仓", color: "text-orange-600", bg: "bg-orange-50", emoji: "📉" },
  SELL: { label: "卖出", color: "text-green-600", bg: "bg-green-50", emoji: "🔻" },
  STRONG_SELL: { label: "强烈卖出", color: "text-green-700", bg: "bg-green-100", emoji: "💀" },
};
