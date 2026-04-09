// 预警信号 API 服务

import apiClient from "./client";
import type { AlertsResponse } from "@/types/alert";

export const alertApi = {
  /** 获取当前所有预警信号 */
  getAlerts: async (): Promise<AlertsResponse> => {
    return apiClient.get("/quotes/alerts");
  },
};
