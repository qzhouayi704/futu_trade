// 主力资金看板 API — 全监控池按主力资金强度排名（只留真大单）

import apiClient from "./client";
import type { ApiResponse } from "@/types";

export const capitalBoardApi = {
  /** 获取主力资金看板排行 */
  getRanking: (limit = 20, includeSniper = true): Promise<ApiResponse> =>
    apiClient.get(`/capital-board/ranking?limit=${limit}&include_sniper=${includeSniper}`),
};
