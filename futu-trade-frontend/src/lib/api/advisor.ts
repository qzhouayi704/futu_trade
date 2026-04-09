// 决策助理 API 客户端

import apiClient from "./client";
import type { ApiResponse } from "@/types";
import type {
  DecisionAdvice,
  PositionHealth,
  AdvisorSummary,
  AdvisorData,
} from "@/types/advisor";

export const advisorApi = {
  /** 获取当前决策建议列表 */
  getAdvices: (): Promise<ApiResponse<DecisionAdvice[]>> =>
    apiClient.get("/advisor/advices"),

  /** 获取持仓健康度摘要 */
  getHealth: (): Promise<
    ApiResponse<{ positions: PositionHealth[]; summary: AdvisorSummary }>
  > => apiClient.get("/advisor/health"),

  /** 忽略某条建议 */
  dismissAdvice: (adviceId: string): Promise<ApiResponse> =>
    apiClient.post(`/advisor/dismiss/${adviceId}`),

  /** 手动触发一次评估 */
  triggerEvaluation: (): Promise<ApiResponse<AdvisorData>> =>
    apiClient.post("/advisor/evaluate"),

  /** 一键执行某条建议 */
  executeAdvice: (adviceId: string): Promise<ApiResponse> =>
    apiClient.post(`/advisor/execute/${adviceId}`),
};
