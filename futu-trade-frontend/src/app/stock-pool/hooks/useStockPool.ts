// 股票池管理 Hook

import { useState, useCallback } from "react";
import { stockApi } from "@/lib/api";
import { useStockPoolStore } from "@/lib/stores";
import type { Plate, Stock, ApiResponse, PaginatedResponse } from "@/types";

export interface InitProgress {
  stage: string;
  progress: number;
  message: string;
  status: "running" | "completed" | "failed";
}

export function useStockPool() {
  const {
    plates,
    stocks,
    platesPage,
    stocksPage,
    platesPageSize,
    stocksPageSize,
    platesTotalCount,
    stocksTotalCount,
    setPlates,
    setStocks,
    setPlatesPage,
    setStocksPage,
    setPlatesPageSize,
    setStocksPageSize,
    setPlatesTotalCount,
    setStocksTotalCount,
  } = useStockPoolStore();

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [initProgress, setInitProgress] = useState<InitProgress | null>(null);

  // 加载板块列表
  const loadPlates = useCallback(
    async (page: number = 1, pageSize: number = 20) => {
      setLoading(true);
      setError(null);

      try {
        const response = (await stockApi.getPlates({
          page,
          limit: pageSize,
        })) as PaginatedResponse<Plate>;

        if (response.success && response.data) {
          setPlates(response.data);
          setPlatesTotalCount(response.meta?.total || response.data.length);
          setPlatesPage(page);
          setPlatesPageSize(pageSize);
        } else {
          throw new Error(response.message || "加载板块失败");
        }
      } catch (err: unknown) {
        const errorMessage = err instanceof Error ? err.message : "加载板块时发生错误";
        setError(errorMessage);
        throw err;
      } finally {
        setLoading(false);
      }
    },
    [setPlates, setPlatesTotalCount, setPlatesPage, setPlatesPageSize]
  );

  // 加载股票列表
  const loadStocks = useCallback(
    async (page: number = 1, pageSize: number = 20) => {
      setLoading(true);
      setError(null);

      try {
        const response = (await stockApi.getStocks({
          page,
          limit: pageSize,
        })) as PaginatedResponse<Stock>;

        if (response.success && response.data) {
          setStocks(response.data);
          setStocksTotalCount(response.meta?.total || response.data.length);
          setStocksPage(page);
          setStocksPageSize(pageSize);
        } else {
          throw new Error(response.message || "加载股票失败");
        }
      } catch (err: unknown) {
        const errorMessage = err instanceof Error ? err.message : "加载股票时发生错误";
        setError(errorMessage);
        throw err;
      } finally {
        setLoading(false);
      }
    },
    [setStocks, setStocksTotalCount, setStocksPage, setStocksPageSize]
  );

  // 添加板块
  const addPlate = useCallback(async (plateCode: string) => {
    setLoading(true);
    setError(null);

    try {
      const response = (await stockApi.addPlate(plateCode)) as ApiResponse<Plate>;

      if (response.success) {
        return response.data;
      } else {
        throw new Error(response.message || "添加板块失败");
      }
    } catch (err: unknown) {
      const errorMessage = err instanceof Error ? err.message : "添加板块时发生错误";
      setError(errorMessage);
      throw err;
    } finally {
      setLoading(false);
    }
  }, []);

  // 删除板块
  const deletePlate = useCallback(async (plateId: number) => {
    setLoading(true);
    setError(null);

    try {
      const response = (await stockApi.deletePlate(plateId)) as ApiResponse<void>;

      if (!response.success) {
        throw new Error(response.message || "删除板块失败");
      }
    } catch (err: unknown) {
      const errorMessage = err instanceof Error ? err.message : "删除板块时发生错误";
      setError(errorMessage);
      throw err;
    } finally {
      setLoading(false);
    }
  }, []);

  // 添加股票
  const addStocks = useCallback(async (stockCodes: string[]) => {
    setLoading(true);
    setError(null);

    try {
      const response = (await stockApi.addStocks(stockCodes)) as ApiResponse<Stock[]>;

      if (response.success) {
        return response.data;
      } else {
        throw new Error(response.message || "添加股票失败");
      }
    } catch (err: unknown) {
      const errorMessage = err instanceof Error ? err.message : "添加股票时发生错误";
      setError(errorMessage);
      throw err;
    } finally {
      setLoading(false);
    }
  }, []);

  // 删除股票
  const deleteStock = useCallback(async (stockId: number) => {
    setLoading(true);
    setError(null);

    try {
      const response = (await stockApi.deleteStock(stockId)) as ApiResponse<void>;

      if (!response.success) {
        throw new Error(response.message || "删除股票失败");
      }
    } catch (err: unknown) {
      const errorMessage = err instanceof Error ? err.message : "删除股票时发生错误";
      setError(errorMessage);
      throw err;
    } finally {
      setLoading(false);
    }
  }, []);

  // 初始化数据
  const initializeData = useCallback(
    async (options: {
      initPlates?: boolean;
      initStocks?: boolean;
      initKline?: boolean;
      initHotStocks?: boolean;
    }) => {
      setLoading(true);
      setError(null);
      setInitProgress({
        stage: "starting",
        progress: 0,
        message: "开始初始化...",
        status: "running",
      });

      try {
        const response = (await stockApi.initializeData(options)) as ApiResponse<any>;

        if (response.success) {
          setInitProgress({
            stage: "completed",
            progress: 100,
            message: "初始化完成",
            status: "completed",
          });
          return response.data;
        } else {
          throw new Error(response.message || "初始化失败");
        }
      } catch (err: unknown) {
        const errorMessage = err instanceof Error ? err.message : "初始化时发生错误";
        setError(errorMessage);
        setInitProgress({
          stage: "failed",
          progress: 0,
          message: errorMessage,
          status: "failed",
        });
        throw err;
      } finally {
        setLoading(false);
      }
    },
    []
  );

  // 增量更新数据
  const refreshData = useCallback(async () => {
    setLoading(true);
    setError(null);
    setInitProgress({
      stage: "starting",
      progress: 0,
      message: "开始更新数据...",
      status: "running",
    });

    try {
      const response = await stockApi.refreshData();

      if (response.success) {
        setInitProgress({
          stage: "completed",
          progress: 100,
          message: response.message || "数据更新完成",
          status: "completed",
        });
        return response.data;
      } else {
        throw new Error(response.message || "更新失败");
      }
    } catch (err: unknown) {
      const errorMessage = err instanceof Error ? err.message : "更新时发生错误";
      console.error('更新错误:', err);
      setError(errorMessage);
      setInitProgress({
        stage: "failed",
        progress: 0,
        message: errorMessage,
        status: "failed",
      });
      throw new Error(errorMessage);
    } finally {
      setLoading(false);
    }
  }, []);

  // 重置数据（清空并重新初始化）
  const resetData = useCallback(async () => {
    setLoading(true);
    setError(null);
    setInitProgress({
      stage: "starting",
      progress: 0,
      message: "开始重置数据...",
      status: "running",
    });

    try {
      const response = await stockApi.resetData();

      if (response.success) {
        setInitProgress({
          stage: "completed",
          progress: 100,
          message: response.message || "数据重置完成",
          status: "completed",
        });
        return response.data;
      } else {
        throw new Error(response.message || "重置失败");
      }
    } catch (err: unknown) {
      const errorMessage = err instanceof Error ? err.message : "重置时发生错误";
      console.error('重置错误:', err);
      setError(errorMessage);
      setInitProgress({
        stage: "failed",
        progress: 0,
        message: errorMessage,
        status: "failed",
      });
      throw new Error(errorMessage);
    } finally {
      setLoading(false);
    }
  }, []);

  return {
    // 状态
    plates,
    stocks,
    platesPage,
    stocksPage,
    platesPageSize,
    stocksPageSize,
    platesTotalCount,
    stocksTotalCount,
    loading,
    error,
    initProgress,

    // 方法
    loadPlates,
    loadStocks,
    addPlate,
    deletePlate,
    addStocks,
    deleteStock,
    initializeData,
    refreshData,
    resetData,
    setInitProgress,
  };
}
