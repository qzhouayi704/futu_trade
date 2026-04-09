// 持仓订单历史 + 单笔止盈 API

import apiClient from "./client";
import type {
  ApiResponse,
  OrderRecord,
  CreateLotTakeProfitRequest,
} from "@/types";

export const positionOrderApi = {
  // 获取某只股票的订单历史（含 FIFO 仓位还原）
  getOrderLots: async (
    stockCode: string
  ): Promise<ApiResponse<OrderRecord[]>> => {
    return apiClient.get(
      `/trading/position-orders/${encodeURIComponent(stockCode)}/lots`
    );
  },

  // 为单笔订单创建止盈配置
  createLotTakeProfit: async (
    data: CreateLotTakeProfitRequest
  ): Promise<
    ApiResponse<{
      id: number;
      stock_code: string;
      deal_id: string;
      trigger_price: number;
      status: string;
    }>
  > => {
    return apiClient.post("/trading/position-orders/take-profit", data);
  },

  // 取消单笔订单的止盈配置
  cancelLotTakeProfit: async (executionId: number): Promise<ApiResponse> => {
    return apiClient.post(
      `/trading/position-orders/take-profit/${executionId}/cancel`
    );
  },

  // 获取某只股票的所有止盈配置
  getLotTakeProfitConfigs: async (
    stockCode: string
  ): Promise<ApiResponse<OrderRecord[]>> => {
    return apiClient.get(
      `/trading/position-orders/${encodeURIComponent(stockCode)}/take-profit`
    );
  },
};
