/**
 * useScalpingSocket - Scalping 实时数据 Socket.IO 事件 Hook
 *
 * 监听所有 Scalping 相关 WebSocket 事件，按 stockCode 过滤，
 * 管理有界缓冲区，股票切换时自动清除旧数据。
 *
 * 需求引用: 12.3, 12.6, 18.6
 */

"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { useSocket } from "@/lib/socket";
import type {
  DeltaUpdateData,
  MomentumIgnitionData,
  PriceLevelData,
  PocUpdateData,
  ScalpingSignalData,
  TrapAlertData,
  FakeBreakoutAlertData,
  TrueBreakoutConfirmData,
  FakeLiquidityAlertData,
  VwapExtensionAlertData,
  VwapExtensionClearData,
  StopLossAlertData,
  TickOutlierData,
  PatternAlertData,
  ActionSignalData,
} from "@/types/scalping";

// ==================== 快照数据类型 ====================

interface SnapshotData {
  stock_code: string;
  delta_data: DeltaUpdateData[];
  poc_data: PocUpdateData | null;
  price_levels: PriceLevelData[];
  vwap_value: number | null;
}

// ==================== 有界缓冲区上限 ====================

const MAX_SIGNALS = 50;
const MAX_DELTA = 60;
const MAX_ALERTS = 20;

// ==================== 事件名常量（snake_case，与后端一致） ====================

const EVENTS = {
  DELTA_UPDATE: "delta_update",
  MOMENTUM_IGNITION: "momentum_ignition",
  PRICE_LEVEL_CREATE: "price_level_create",
  PRICE_LEVEL_REMOVE: "price_level_remove",
  PRICE_LEVEL_BREAK: "price_level_break",
  POC_UPDATE: "poc_update",
  SCALPING_SIGNAL: "scalping_signal",
  TRAP_ALERT: "trap_alert",
  FAKE_BREAKOUT_ALERT: "fake_breakout_alert",
  TRUE_BREAKOUT_CONFIRM: "true_breakout_confirm",
  FAKE_LIQUIDITY_ALERT: "fake_liquidity_alert",
  VWAP_EXTENSION_ALERT: "vwap_extension_alert",
  VWAP_EXTENSION_CLEAR: "vwap_extension_clear",
  STOP_LOSS_ALERT: "stop_loss_alert",
  TICK_OUTLIER: "tick_outlier",
  PATTERN_ALERT: "pattern_alert",
  ACTION_SIGNAL: "action_signal",
} as const;

// ==================== 返回类型 ====================

export interface UseScalpingSocketReturn {
  deltaData: DeltaUpdateData[];
  pocData: PocUpdateData | null;
  priceLevels: PriceLevelData[];
  signals: ScalpingSignalData[];
  isConnected: boolean;
  momentumIgnitions: MomentumIgnitionData[];
  trapAlerts: TrapAlertData[];
  fakeBreakoutAlerts: FakeBreakoutAlertData[];
  trueBreakoutConfirms: TrueBreakoutConfirmData[];
  fakeLiquidityAlerts: FakeLiquidityAlertData[];
  vwapExtension: VwapExtensionAlertData | null;
  vwapData: { vwap: number; timestamp: string } | null;
  stopLossAlerts: StopLossAlertData[];
  tickOutliers: TickOutlierData[];
  patternAlerts: PatternAlertData[];
  actionSignals: ActionSignalData[];
}

// ==================== 工具函数 ====================

/** 向有界数组末尾追加，超出上限时移除最旧的 */
function appendBounded<T>(arr: T[], item: T, max: number): T[] {
  const next = [...arr, item];
  return next.length > max ? next.slice(next.length - max) : next;
}

// ==================== Hook 实现 ====================

export function useScalpingSocket(stockCode: string): UseScalpingSocketReturn {
  const { socket, isConnected } = useSocket();

  // 核心状态
  const [deltaData, setDeltaData] = useState<DeltaUpdateData[]>([]);
  const [pocData, setPocData] = useState<PocUpdateData | null>(null);
  const [priceLevels, setPriceLevels] = useState<PriceLevelData[]>([]);
  const [signals, setSignals] = useState<ScalpingSignalData[]>([]);
  const [momentumIgnitions, setMomentumIgnitions] = useState<MomentumIgnitionData[]>([]);

  // 防诱多/诱空状态
  const [trapAlerts, setTrapAlerts] = useState<TrapAlertData[]>([]);
  const [fakeBreakoutAlerts, setFakeBreakoutAlerts] = useState<FakeBreakoutAlertData[]>([]);
  const [trueBreakoutConfirms, setTrueBreakoutConfirms] = useState<TrueBreakoutConfirmData[]>([]);
  const [fakeLiquidityAlerts, setFakeLiquidityAlerts] = useState<FakeLiquidityAlertData[]>([]);
  const [vwapExtension, setVwapExtension] = useState<VwapExtensionAlertData | null>(null);
  const [vwapData, setVwapData] = useState<{ vwap: number; timestamp: string } | null>(null);

  // 止损与异常大单状态
  const [stopLossAlerts, setStopLossAlerts] = useState<StopLossAlertData[]>([]);
  const [tickOutliers, setTickOutliers] = useState<TickOutlierData[]>([]);

  // 行为模式预警 + 行动评分
  const [patternAlerts, setPatternAlerts] = useState<PatternAlertData[]>([]);
  const [actionSignals, setActionSignals] = useState<ActionSignalData[]>([]);

  // 用 ref 跟踪当前 stockCode，避免闭包陈旧问题
  const stockCodeRef = useRef(stockCode);
  stockCodeRef.current = stockCode;

  // 股票切换时清除旧数据并加载快照
  useEffect(() => {
    setDeltaData([]);
    setPocData(null);
    setPriceLevels([]);
    setSignals([]);
    setMomentumIgnitions([]);
    setTrapAlerts([]);
    setFakeBreakoutAlerts([]);
    setTrueBreakoutConfirms([]);
    setFakeLiquidityAlerts([]);
    setVwapExtension(null);
    setVwapData(null);
    setStopLossAlerts([]);
    setTickOutliers([]);
    setPatternAlerts([]);
    setActionSignals([]);

    if (!stockCode) return;

    let cancelled = false;

    // 加载快照数据填充初始状态
    fetch(`/api/scalping/snapshot/${encodeURIComponent(stockCode)}`)
      .then((res) => res.json())
      .then((json: { success: boolean; data?: SnapshotData }) => {
        if (cancelled || !json.success || !json.data) return;
        const d = json.data;

        if (d.delta_data?.length) {
          setDeltaData(d.delta_data.slice(-MAX_DELTA));
        }
        if (d.poc_data) {
          setPocData(d.poc_data as PocUpdateData);
        }
        if (d.price_levels?.length) {
          setPriceLevels(d.price_levels as PriceLevelData[]);
        }
        if (d.vwap_value != null) {
          setVwapData({ vwap: d.vwap_value, timestamp: new Date().toISOString() });
        }
      })
      .catch(() => {
        // 快照加载失败时静默处理，等待 WebSocket 推送
      });

    return () => { cancelled = true; };
  }, [stockCode]);

  // ==================== 事件处理器 ====================

  const matchStock = useCallback(
    (data: { stock_code: string }) => data.stock_code === stockCodeRef.current,
    [],
  );

  const handleDeltaUpdate = useCallback(
    (data: DeltaUpdateData) => {
      if (!matchStock(data)) return;
      setDeltaData((prev) => appendBounded(prev, data, MAX_DELTA));
    },
    [matchStock],
  );

  const handleMomentumIgnition = useCallback(
    (data: MomentumIgnitionData) => {
      if (!matchStock(data)) return;
      setMomentumIgnitions((prev) => appendBounded(prev, data, MAX_ALERTS));
    },
    [matchStock],
  );

  const handlePriceLevelCreate = useCallback(
    (data: PriceLevelData) => {
      if (!matchStock(data)) return;
      setPriceLevels((prev) => [...prev, data]);
    },
    [matchStock],
  );

  const handlePriceLevelRemove = useCallback(
    (data: PriceLevelData) => {
      if (!matchStock(data)) return;
      setPriceLevels((prev) => prev.filter((l) => l.price !== data.price));
    },
    [matchStock],
  );

  const handlePriceLevelBreak = useCallback(
    (data: PriceLevelData) => {
      if (!matchStock(data)) return;
      setPriceLevels((prev) => prev.filter((l) => l.price !== data.price));
    },
    [matchStock],
  );

  const handlePocUpdate = useCallback(
    (data: PocUpdateData) => {
      if (!matchStock(data)) return;
      setPocData(data);
    },
    [matchStock],
  );

  const handleScalpingSignal = useCallback(
    (data: ScalpingSignalData) => {
      if (!matchStock(data)) return;
      setSignals((prev) => appendBounded(prev, data, MAX_SIGNALS));
    },
    [matchStock],
  );

  const handleTrapAlert = useCallback(
    (data: TrapAlertData) => {
      if (!matchStock(data)) return;
      setTrapAlerts((prev) => appendBounded(prev, data, MAX_ALERTS));
    },
    [matchStock],
  );

  const handleFakeBreakoutAlert = useCallback(
    (data: FakeBreakoutAlertData) => {
      if (!matchStock(data)) return;
      setFakeBreakoutAlerts((prev) => appendBounded(prev, data, MAX_ALERTS));
    },
    [matchStock],
  );

  const handleTrueBreakoutConfirm = useCallback(
    (data: TrueBreakoutConfirmData) => {
      if (!matchStock(data)) return;
      setTrueBreakoutConfirms((prev) => appendBounded(prev, data, MAX_ALERTS));
    },
    [matchStock],
  );

  const handleFakeLiquidityAlert = useCallback(
    (data: FakeLiquidityAlertData) => {
      if (!matchStock(data)) return;
      setFakeLiquidityAlerts((prev) => appendBounded(prev, data, MAX_ALERTS));
    },
    [matchStock],
  );

  const handleVwapExtensionAlert = useCallback(
    (data: VwapExtensionAlertData) => {
      if (!matchStock(data)) return;
      setVwapExtension(data);
      setVwapData({ vwap: data.vwap_value, timestamp: data.timestamp });
    },
    [matchStock],
  );

  const handleVwapExtensionClear = useCallback(
    (data: VwapExtensionClearData) => {
      if (!matchStock(data)) return;
      setVwapExtension(null);
      setVwapData({ vwap: data.vwap_value, timestamp: data.timestamp });
    },
    [matchStock],
  );

  const handleStopLossAlert = useCallback(
    (data: StopLossAlertData) => {
      if (!matchStock(data)) return;
      setStopLossAlerts((prev) => appendBounded(prev, data, MAX_ALERTS));
    },
    [matchStock],
  );

  const handleTickOutlier = useCallback(
    (data: TickOutlierData) => {
      if (!matchStock(data)) return;
      setTickOutliers((prev) => appendBounded(prev, data, MAX_ALERTS));
    },
    [matchStock],
  );

  const handlePatternAlert = useCallback(
    (data: PatternAlertData) => {
      if (!matchStock(data)) return;
      setPatternAlerts((prev) => appendBounded(prev, data, MAX_ALERTS));
    },
    [matchStock],
  );

  const handleActionSignal = useCallback(
    (data: ActionSignalData) => {
      if (!matchStock(data)) return;
      setActionSignals((prev) => appendBounded(prev, data, MAX_ALERTS));
    },
    [matchStock],
  );

  // ==================== 注册/注销事件监听 ====================

  useEffect(() => {
    if (!socket) return;

    socket.on(EVENTS.DELTA_UPDATE, handleDeltaUpdate);
    socket.on(EVENTS.MOMENTUM_IGNITION, handleMomentumIgnition);
    socket.on(EVENTS.PRICE_LEVEL_CREATE, handlePriceLevelCreate);
    socket.on(EVENTS.PRICE_LEVEL_REMOVE, handlePriceLevelRemove);
    socket.on(EVENTS.PRICE_LEVEL_BREAK, handlePriceLevelBreak);
    socket.on(EVENTS.POC_UPDATE, handlePocUpdate);
    socket.on(EVENTS.SCALPING_SIGNAL, handleScalpingSignal);
    socket.on(EVENTS.TRAP_ALERT, handleTrapAlert);
    socket.on(EVENTS.FAKE_BREAKOUT_ALERT, handleFakeBreakoutAlert);
    socket.on(EVENTS.TRUE_BREAKOUT_CONFIRM, handleTrueBreakoutConfirm);
    socket.on(EVENTS.FAKE_LIQUIDITY_ALERT, handleFakeLiquidityAlert);
    socket.on(EVENTS.VWAP_EXTENSION_ALERT, handleVwapExtensionAlert);
    socket.on(EVENTS.VWAP_EXTENSION_CLEAR, handleVwapExtensionClear);
    socket.on(EVENTS.STOP_LOSS_ALERT, handleStopLossAlert);
    socket.on(EVENTS.TICK_OUTLIER, handleTickOutlier);
    socket.on(EVENTS.PATTERN_ALERT, handlePatternAlert);
    socket.on(EVENTS.ACTION_SIGNAL, handleActionSignal);

    return () => {
      socket.off(EVENTS.DELTA_UPDATE, handleDeltaUpdate);
      socket.off(EVENTS.MOMENTUM_IGNITION, handleMomentumIgnition);
      socket.off(EVENTS.PRICE_LEVEL_CREATE, handlePriceLevelCreate);
      socket.off(EVENTS.PRICE_LEVEL_REMOVE, handlePriceLevelRemove);
      socket.off(EVENTS.PRICE_LEVEL_BREAK, handlePriceLevelBreak);
      socket.off(EVENTS.POC_UPDATE, handlePocUpdate);
      socket.off(EVENTS.SCALPING_SIGNAL, handleScalpingSignal);
      socket.off(EVENTS.TRAP_ALERT, handleTrapAlert);
      socket.off(EVENTS.FAKE_BREAKOUT_ALERT, handleFakeBreakoutAlert);
      socket.off(EVENTS.TRUE_BREAKOUT_CONFIRM, handleTrueBreakoutConfirm);
      socket.off(EVENTS.FAKE_LIQUIDITY_ALERT, handleFakeLiquidityAlert);
      socket.off(EVENTS.VWAP_EXTENSION_ALERT, handleVwapExtensionAlert);
      socket.off(EVENTS.VWAP_EXTENSION_CLEAR, handleVwapExtensionClear);
      socket.off(EVENTS.STOP_LOSS_ALERT, handleStopLossAlert);
      socket.off(EVENTS.TICK_OUTLIER, handleTickOutlier);
      socket.off(EVENTS.PATTERN_ALERT, handlePatternAlert);
      socket.off(EVENTS.ACTION_SIGNAL, handleActionSignal);
    };
  }, [
    socket,
    handleDeltaUpdate,
    handleMomentumIgnition,
    handlePriceLevelCreate,
    handlePriceLevelRemove,
    handlePriceLevelBreak,
    handlePocUpdate,
    handleScalpingSignal,
    handleTrapAlert,
    handleFakeBreakoutAlert,
    handleTrueBreakoutConfirm,
    handleFakeLiquidityAlert,
    handleVwapExtensionAlert,
    handleVwapExtensionClear,
    handleStopLossAlert,
    handleTickOutlier,
    handlePatternAlert,
    handleActionSignal,
  ]);

  return {
    deltaData,
    pocData,
    priceLevels,
    signals,
    isConnected,
    momentumIgnitions,
    trapAlerts,
    fakeBreakoutAlerts,
    trueBreakoutConfirms,
    fakeLiquidityAlerts,
    vwapExtension,
    vwapData,
    stopLossAlerts,
    tickOutliers,
    patternAlerts,
    actionSignals,
  };
}
