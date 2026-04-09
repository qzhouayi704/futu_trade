// 股票池状态管理

import { create } from "zustand";
import type { Plate, Stock } from "@/types";

interface StockPoolState {
  // 数据状态
  plates: Plate[];
  stocks: Stock[];
  initialized: boolean;

  // 分页状态
  platesPage: number;
  platesPageSize: number;
  platesTotalPages: number;
  platesTotalCount: number;

  stocksPage: number;
  stocksPageSize: number;
  stocksTotalPages: number;
  stocksTotalCount: number;

  // 筛选条件
  platesSearch: string;
  platesMarket: string;
  stocksSearch: string;
  stocksMarket: string;

  // 初始化进度
  initProgress: number;
  initMessage: string;

  // Actions
  setPlates: (plates: Plate[], totalPages?: number) => void;
  setStocks: (stocks: Stock[], totalPages?: number) => void;
  setInitialized: (initialized: boolean) => void;

  // 分页
  setPlatesPage: (page: number) => void;
  setStocksPage: (page: number) => void;
  setPlatesPageSize: (pageSize: number) => void;
  setStocksPageSize: (pageSize: number) => void;
  setPlatesTotalCount: (count: number) => void;
  setStocksTotalCount: (count: number) => void;

  // 筛选
  setPlatesSearch: (search: string) => void;
  setPlatesMarket: (market: string) => void;
  setStocksSearch: (search: string) => void;
  setStocksMarket: (market: string) => void;

  // 初始化
  setInitProgress: (progress: number, message: string) => void;

  // 操作
  addPlate: (plate: Plate) => void;
  removePlate: (plateId: number) => void;
  addStock: (stock: Stock) => void;
  removeStock: (stockId: number) => void;

  reset: () => void;
}

const initialState = {
  plates: [],
  stocks: [],
  initialized: false,
  platesPage: 1,
  platesPageSize: 20,
  platesTotalPages: 1,
  platesTotalCount: 0,
  stocksPage: 1,
  stocksPageSize: 20,
  stocksTotalPages: 1,
  stocksTotalCount: 0,
  platesSearch: "",
  platesMarket: "",
  stocksSearch: "",
  stocksMarket: "",
  initProgress: 0,
  initMessage: "",
};

export const useStockPoolStore = create<StockPoolState>((set) => ({
  ...initialState,

  setPlates: (plates, totalPages) =>
    set((state) => ({
      plates,
      platesTotalPages: totalPages ?? state.platesTotalPages,
    })),

  setStocks: (stocks, totalPages) =>
    set((state) => ({
      stocks,
      stocksTotalPages: totalPages ?? state.stocksTotalPages,
    })),

  setInitialized: (initialized) => set({ initialized }),

  setPlatesPage: (page) => set({ platesPage: page }),

  setStocksPage: (page) => set({ stocksPage: page }),

  setPlatesPageSize: (pageSize) => set({ platesPageSize: pageSize }),

  setStocksPageSize: (pageSize) => set({ stocksPageSize: pageSize }),

  setPlatesTotalCount: (count) => set({ platesTotalCount: count }),

  setStocksTotalCount: (count) => set({ stocksTotalCount: count }),

  setPlatesSearch: (search) => set({ platesSearch: search }),

  setPlatesMarket: (market) => set({ platesMarket: market }),

  setStocksSearch: (search) => set({ stocksSearch: search }),

  setStocksMarket: (market) => set({ stocksMarket: market }),

  setInitProgress: (progress, message) =>
    set({ initProgress: progress, initMessage: message }),

  addPlate: (plate) =>
    set((state) => ({
      plates: [plate, ...state.plates],
    })),

  removePlate: (plateId) =>
    set((state) => ({
      plates: state.plates.filter((p) => p.id !== plateId),
    })),

  addStock: (stock) =>
    set((state) => ({
      stocks: [stock, ...state.stocks],
    })),

  removeStock: (stockId) =>
    set((state) => ({
      stocks: state.stocks.filter((s) => s.id !== stockId),
    })),

  reset: () => set(initialState),
}));
