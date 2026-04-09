// 股票池 API

import apiClient from "./client";
import type { ApiResponse, StockPool, Plate, Stock, PlateDetail, HighTurnoverResponse, TopHotResponse } from "@/types";

export const stockApi = {
  // 获取股票池数据
  getStockPool: async (): Promise<ApiResponse<StockPool>> => {
    return apiClient.get("/stocks/pool");
  },

  // 获取板块列表
  getPlates: async (params?: {
    page?: number;
    limit?: number;
    search?: string;
    market?: string;
  }): Promise<ApiResponse<Plate[]>> => {
    return apiClient.get("/stocks/plates", { params });
  },

  // 获取可用板块列表
  getAvailablePlates: async (params?: {
    search?: string;
    market?: string;
  }): Promise<ApiResponse<Plate[]>> => {
    return apiClient.get("/plates/available", { params });
  },

  // 添加板块
  addPlate: async (plateCode: string): Promise<ApiResponse> => {
    return apiClient.post("/plates/add", { plate_code: plateCode });
  },

  // 批量添加板块
  batchAddPlates: async (plateCodes: string[]): Promise<ApiResponse> => {
    return apiClient.post("/plates/batch-add", { plate_codes: plateCodes });
  },

  // 删除板块
  deletePlate: async (plateId: number): Promise<ApiResponse> => {
    return apiClient.delete(`/plates/${plateId}`);
  },

  // 获取股票列表
  getStocks: async (params?: {
    page?: number;
    limit?: number;
    search?: string;
    market?: string;
  }): Promise<ApiResponse<Stock[]>> => {
    return apiClient.get("/stocks/pool", { params });
  },

  // 添加股票
  addStock: async (data: {
    stock_codes: string[];
    plate_id?: number;
    is_manual?: boolean;
  }): Promise<ApiResponse> => {
    return apiClient.post("/stocks", data);
  },

  // 添加股票（简化版）
  addStocks: async (stockCodes: string[]): Promise<ApiResponse> => {
    return apiClient.post("/stocks", {
      stock_codes: stockCodes,
      is_manual: true
    });
  },

  // 删除股票
  deleteStock: async (stockId: number): Promise<ApiResponse> => {
    return apiClient.delete(`/stocks/${stockId}`);
  },

  // 获取板块详情
  getPlateDetail: async (
    plateCode: string,
    params?: { page?: number; limit?: number; search?: string }
  ): Promise<ApiResponse<PlateDetail>> => {
    return apiClient.get(`/plates/${plateCode}/detail`, { params });
  },

  // 获取板块信息（不含股票列表）
  getPlateByCode: async (plateCode: string): Promise<ApiResponse<Plate>> => {
    return apiClient.get(`/plates/${plateCode}`);
  },

  // 获取板块下的股票列表
  getStocksByPlate: async (plateCode: string): Promise<ApiResponse<Stock[]>> => {
    return apiClient.get(`/plates/${plateCode}/stocks`);
  },

  // 获取K线数据
  getKlineData: async (
    stockCode: string,
    days: number = 30
  ): Promise<ApiResponse<unknown>> => {
    return apiClient.get(`/stocks/kline/${stockCode}`, { params: { days } });
  },

  // 初始化数据
  initData: async (forceRefresh: boolean = false): Promise<ApiResponse> => {
    return apiClient.post("/stocks/init", { force_refresh: forceRefresh });
  },

  // 初始化数据（带选项）
  initializeData: async (options: {
    initPlates?: boolean;
    initStocks?: boolean;
    initKline?: boolean;
    initHotStocks?: boolean;
  }): Promise<ApiResponse> => {
    // 根据选项决定是否强制刷新
    const forceRefresh = options.initPlates || options.initStocks || false;
    return apiClient.post("/stocks/init", { force_refresh: forceRefresh });
  },

  // 增量更新数据（不删除现有数据）
  refreshData: async (): Promise<ApiResponse> => {
    return apiClient.post("/stocks/refresh");
  },

  // 重置数据（清空并重新初始化）
  resetData: async (): Promise<ApiResponse> => {
    return apiClient.post("/stocks/init", { force_refresh: true });
  },

  // 获取初始化状态
  getInitStatus: async (): Promise<ApiResponse> => {
    return apiClient.get("/stocks/init/status");
  },

  // 获取热门股票
  getTopHotStocks: async (params?: {
    limit?: number;
    market?: string;
    search?: string;
  }): Promise<ApiResponse<TopHotResponse>> => {
    return apiClient.get("/stocks/top-hot", { params });
  },

  // 获取未订阅股票列表
  getUnsubscribedStocks: async (params?: {
    market?: string;
    search?: string;
    page?: number;
    limit?: number;
  }): Promise<ApiResponse<any>> => {
    return apiClient.get("/stocks/unsubscribed", { params });
  },

  // 触发重新筛选活跃度（异步，后台执行并通过 WebSocket 推送进度）
  refilterActivity: async (): Promise<ApiResponse<any>> => {
    return apiClient.post("/stocks/refilter-activity");
  },

  // 获取高换手率股票列表
  getHighTurnoverStocks: async (params?: {
    limit?: number;
    market?: string;
    min_turnover_rate?: number;
    search?: string;
    include_ticker_analysis?: boolean;
  }): Promise<ApiResponse<HighTurnoverResponse>> => {
    return apiClient.get("/stocks/high-turnover", { params });
  },

  // 获取自选股列表
  getWatchlist: async (): Promise<ApiResponse<{ codes: string[]; count: number }>> => {
    return apiClient.get("/watchlist");
  },

  // 添加股票到自选股
  addToWatchlist: async (codes: string[]): Promise<ApiResponse<{ codes: string[] }>> => {
    return apiClient.post("/watchlist", { codes });
  },

  // 从自选股移除
  removeFromWatchlist: async (code: string): Promise<ApiResponse<{ codes: string[] }>> => {
    return apiClient.delete(`/watchlist/${code}`);
  },

  // 重置活跃度记录
  resetActivityRecords: async (): Promise<ApiResponse<any>> => {
    return apiClient.post("/stocks/reset-activity-records");
  },
};
