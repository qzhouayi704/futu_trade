// 监控状态管理

import { create } from "zustand";
import type {
  Stock,
  TradeSignal,
  Plate,
  EnabledStrategy,
  SignalsByStrategy,
} from "@/types";

interface MonitorState {
  // 监控状态
  isMonitoring: boolean;
  monitorStartTime: string | null;

  // 单策略（向后兼容）
  activeStrategyId: string | null;
  activeStrategyName: string | null;
  activePresetName: string | null;

  // 多策略
  enabledStrategies: EnabledStrategy[];
  autoTradeStrategyId: string | null;
  signalsByStrategy: SignalsByStrategy;

  // 股票池数据
  stocks: Stock[];
  plates: Plate[];

  // 信号数据
  todaySignals: TradeSignal[];
  historySignals: TradeSignal[];

  // 过滤选项
  filterHotOnly: boolean;

  // Actions
  setMonitoring: (isMonitoring: boolean, startTime?: string | null) => void;
  setActiveStrategy: (strategyId: string, strategyName: string, presetName: string) => void;

  // 多策略 Actions
  setEnabledStrategies: (strategies: EnabledStrategy[]) => void;
  setAutoTradeStrategyId: (strategyId: string | null) => void;
  setSignalsByStrategy: (signals: SignalsByStrategy) => void;
  updateStrategySignalCount: (
    strategyId: string,
    buyCount: number,
    sellCount: number
  ) => void;

  updateStocks: (stocks: Stock[]) => void;
  updatePlates: (plates: Plate[]) => void;
  addSignal: (signal: TradeSignal) => void;
  setTodaySignals: (signals: TradeSignal[]) => void;
  setHistorySignals: (signals: TradeSignal[]) => void;
  clearSignals: () => void;
  setFilterHotOnly: (filterHotOnly: boolean) => void;
  reset: () => void;
}

const initialState = {
  isMonitoring: false,
  monitorStartTime: null,
  activeStrategyId: null,
  activeStrategyName: null,
  activePresetName: null,
  enabledStrategies: [] as EnabledStrategy[],
  autoTradeStrategyId: null as string | null,
  signalsByStrategy: {} as SignalsByStrategy,
  stocks: [] as Stock[],
  plates: [] as Plate[],
  todaySignals: [] as TradeSignal[],
  historySignals: [] as TradeSignal[],
  filterHotOnly: false,
};

export const useMonitorStore = create<MonitorState>((set) => ({
  ...initialState,

  setMonitoring: (isMonitoring, startTime = null) =>
    set({ isMonitoring, monitorStartTime: startTime }),

  setActiveStrategy: (strategyId, strategyName, presetName) =>
    set({
      activeStrategyId: strategyId,
      activeStrategyName: strategyName,
      activePresetName: presetName,
    }),

  setEnabledStrategies: (strategies) =>
    set({ enabledStrategies: strategies }),

  setAutoTradeStrategyId: (strategyId) =>
    set({ autoTradeStrategyId: strategyId }),

  setSignalsByStrategy: (signals) =>
    set({ signalsByStrategy: signals }),

  updateStrategySignalCount: (strategyId, buyCount, sellCount) =>
    set((state) => ({
      enabledStrategies: state.enabledStrategies.map((s) =>
        s.strategy_id === strategyId
          ? { ...s, signal_count_buy: buyCount, signal_count_sell: sellCount }
          : s
      ),
    })),

  updateStocks: (stocks) => set({ stocks }),
  updatePlates: (plates) => set({ plates }),

  addSignal: (signal) =>
    set((state) => ({
      todaySignals: [signal, ...state.todaySignals],
    })),

  setTodaySignals: (signals) => set({ todaySignals: signals }),
  setHistorySignals: (signals) => set({ historySignals: signals }),
  clearSignals: () => set({ todaySignals: [], historySignals: [] }),
  setFilterHotOnly: (filterHotOnly) => set({ filterHotOnly }),
  reset: () => set(initialState),
}));
