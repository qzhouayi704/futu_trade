// 交易 API

import apiClient from "./client";
import type {
  ApiResponse,
  TradeSignal,
  Position,
  BackendPosition,
  TradeRecord,
  OrderForm,
  PositionLot,
  TakeProfitTask,
} from "@/types";

export const tradeApi = {
  // 获取交易信号
  getSignals: async (params?: {
    type?: "buy" | "sell" | "all";
    strategy_id?: string;
    limit?: number;
  }): Promise<ApiResponse<TradeSignal[]>> => {
    return apiClient.get("/trading/signals", { params });
  },

  // 执行交易
  executeTrade: async (order: OrderForm): Promise<ApiResponse> => {
    return apiClient.post("/trading/execute", order);
  },

  // 获取持仓信息
  getPositions: async (): Promise<ApiResponse<Position[]>> => {
    return apiClient.get("/trading/positions");
  },

  // 独立获取持仓信息（自动连接交易API，不依赖监控状态）
  getPositionsStandalone: async (): Promise<
    ApiResponse<{
      positions: BackendPosition[];
      auto_connected: boolean;
      trade_api_status: {
        is_connected: boolean;
        is_unlocked: boolean;
      };
    }>
  > => {
    return apiClient.get("/trading/positions/standalone");
  },

  // 获取交易记录
  getTradeRecords: async (params?: {
    limit?: number;
    status?: string;
  }): Promise<ApiResponse<TradeRecord[]>> => {
    return apiClient.get("/trading/records", { params });
  },

  // 获取交易连接状态
  getConnectionStatus: async (): Promise<
    ApiResponse<{ connected: boolean; message?: string }>
  > => {
    return apiClient.get("/trading/status");
  },

  // 连接富途交易API
  connectTrading: async (): Promise<ApiResponse> => {
    return apiClient.post("/trading/connect");
  },

  // 获取监控任务列表
  getMonitorTasks: async (params?: {
    status?: string;
    limit?: number;
  }): Promise<ApiResponse<unknown[]>> => {
    return apiClient.get("/trading/monitor/tasks", { params });
  },

  // 添加监控任务
  addMonitorTask: async (data: {
    stock_code: string;
    stock_name: string;
    direction: "buy" | "sell";
    target_price: number;
    quantity: number;
    stop_loss_price?: number;
  }): Promise<ApiResponse> => {
    return apiClient.post("/trading/monitor/tasks", data);
  },

  // 取消监控任务
  cancelMonitorTask: async (taskId: number): Promise<ApiResponse> => {
    return apiClient.post(`/trading/monitor/tasks/${taskId}/cancel`);
  },

  // ==================== 分仓止盈 ====================

  // 获取分仓信息
  getPositionLots: async (stockCode: string): Promise<ApiResponse<PositionLot[]>> => {
    return apiClient.get(`/trading/take-profit/lots/${stockCode}`);
  },

  // 创建止盈任务
  createTakeProfitTask: async (data: {
    stock_code: string;
    take_profit_pct: number;
  }): Promise<ApiResponse<TakeProfitTask>> => {
    return apiClient.post("/trading/take-profit/tasks", data);
  },

  // 获取所有止盈任务
  getTakeProfitTasks: async (): Promise<ApiResponse<TakeProfitTask[]>> => {
    return apiClient.get("/trading/take-profit/tasks");
  },

  // 获取止盈任务详情
  getTakeProfitDetail: async (stockCode: string): Promise<ApiResponse<TakeProfitTask>> => {
    return apiClient.get(`/trading/take-profit/tasks/${stockCode}`);
  },

  // 取消止盈任务
  cancelTakeProfitTask: async (stockCode: string): Promise<ApiResponse> => {
    return apiClient.post(`/trading/take-profit/tasks/${stockCode}/cancel`);
  },
};
