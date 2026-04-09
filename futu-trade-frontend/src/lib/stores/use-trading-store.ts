// 交易状态管理

import { create } from "zustand";
import type { TradeSignal, Position, TradeRecord } from "@/types";

interface TradingState {
  // 交易连接状态
  isConnected: boolean;
  connectionMessage: string;

  // 交易信号
  signals: TradeSignal[];

  // 持仓信息
  positions: Position[];
  totalMarketValue: number;
  totalPL: number;
  totalPLRatio: number;

  // 交易记录
  records: TradeRecord[];

  // 下单表单状态
  selectedSignal: TradeSignal | null;
  orderFormVisible: boolean;

  // Actions
  setConnectionStatus: (isConnected: boolean, message?: string) => void;
  setSignals: (signals: TradeSignal[]) => void;
  addSignal: (signal: TradeSignal) => void;
  updateSignal: (signalId: number, updates: Partial<TradeSignal>) => void;

  setPositions: (positions: Position[]) => void;
  updatePositionsSummary: (
    totalMarketValue: number,
    totalPL: number,
    totalPLRatio: number
  ) => void;

  setRecords: (records: TradeRecord[]) => void;
  addRecord: (record: TradeRecord) => void;

  setSelectedSignal: (signal: TradeSignal | null) => void;
  setOrderFormVisible: (visible: boolean) => void;

  reset: () => void;
}

const initialState = {
  isConnected: false,
  connectionMessage: "",
  signals: [],
  positions: [],
  totalMarketValue: 0,
  totalPL: 0,
  totalPLRatio: 0,
  records: [],
  selectedSignal: null,
  orderFormVisible: false,
};

export const useTradingStore = create<TradingState>((set) => ({
  ...initialState,

  setConnectionStatus: (isConnected, message = "") =>
    set({ isConnected, connectionMessage: message }),

  setSignals: (signals) => set({ signals }),

  addSignal: (signal) =>
    set((state) => ({
      signals: [signal, ...state.signals],
    })),

  updateSignal: (signalId, updates) =>
    set((state) => ({
      signals: state.signals.map((signal) =>
        signal.id === signalId ? { ...signal, ...updates } : signal
      ),
    })),

  setPositions: (positions) => set({ positions }),

  updatePositionsSummary: (totalMarketValue, totalPL, totalPLRatio) =>
    set({ totalMarketValue, totalPL, totalPLRatio }),

  setRecords: (records) => set({ records }),

  addRecord: (record) =>
    set((state) => ({
      records: [record, ...state.records],
    })),

  setSelectedSignal: (signal) => set({ selectedSignal: signal }),

  setOrderFormVisible: (visible) => set({ orderFormVisible: visible }),

  reset: () => set(initialState),
}));
