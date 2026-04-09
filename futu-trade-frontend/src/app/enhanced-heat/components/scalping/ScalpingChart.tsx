/**
 * ScalpingChart - 三合一作战主图容器
 *
 * 创建 TVLC chart 实例，管理 CandlestickSeries（K 线主图），
 * 协调 DeltaHistogram、PocOverlay、PriceLevelLines、VwapOverlay、SignalPanel 子组件。
 * 渲染诱多/诱空、假突破、虚假流动性、止损提示、异常大单标记。
 *
 * 需求引用: 12.4, 12.7, 13.3, 13.4, 14.5, 15.4, 18.6
 */

"use client";

import { useEffect, useRef, useState, useCallback, useMemo } from "react";
import { createChart, ColorType } from "lightweight-charts";
import type {
  IChartApi,
  ISeriesApi,
  SeriesMarker,
  Time,
  UTCTimestamp,
} from "lightweight-charts";
import type {
  TrapAlertData,
  FakeBreakoutAlertData,
  FakeLiquidityAlertData,
  StopLossAlertData,
  TickOutlierData,
} from "@/types/scalping";
import { useScalpingSocket } from "./useScalpingSocket";
import { DeltaHistogram } from "./DeltaHistogram";
import { PocOverlay } from "./PocOverlay";
import { PriceLevelLines } from "./PriceLevelLines";
import { VwapOverlay } from "./VwapOverlay";
import { SignalPanel } from "./SignalPanel";

// ==================== 组件接口 ====================

interface ScalpingChartProps {
  stockCode: string;
  height?: number;
  /** managed 模式：跳过自动启停引擎，由外部统一管理 */
  managed?: boolean;
}

// ==================== 常量 ====================

const DEFAULT_HEIGHT = 500;

const CHART_OPTIONS = {
  layout: {
    background: { type: ColorType.Solid, color: "#1a1a2e" },
    textColor: "#d1d5db",
  },
  grid: {
    vertLines: { color: "#2a2a3e" },
    horzLines: { color: "#2a2a3e" },
  },
  crosshair: { mode: 0 as const },
  rightPriceScale: { borderColor: "#2a2a3e" },
  timeScale: {
    borderColor: "#2a2a3e",
    timeVisible: true,
    secondsVisible: true,
  },
};

const CANDLE_OPTIONS = {
  upColor: "#26a69a",
  downColor: "#ef5350",
  borderUpColor: "#26a69a",
  borderDownColor: "#ef5350",
  wickUpColor: "#26a69a",
  wickDownColor: "#ef5350",
};

// ==================== 工具函数 ====================

/** ISO 时间戳转 TVLC UTCTimestamp（Unix 秒） */
function toUTCTimestamp(isoTimestamp: string): UTCTimestamp {
  return Math.floor(new Date(isoTimestamp).getTime() / 1000) as UTCTimestamp;
}

/** 从诱多/诱空警报生成标记 */
function trapAlertsToMarkers(alerts: TrapAlertData[]): SeriesMarker<Time>[] {
  return alerts.map((a) => {
    const isBull = a.trap_type === "bull_trap";
    return {
      time: toUTCTimestamp(a.timestamp),
      position: isBull ? "aboveBar" : "belowBar",
      color: isBull ? "#ef5350" : "#26a69a",
      shape: isBull ? "arrowDown" : "arrowUp",
      text: isBull ? "诱多" : "诱空",
    } as SeriesMarker<Time>;
  });
}

/** 从假突破警报生成标记 */
function fakeBreakoutToMarkers(
  alerts: FakeBreakoutAlertData[],
): SeriesMarker<Time>[] {
  return alerts.map(
    (a) =>
      ({
        time: toUTCTimestamp(a.timestamp),
        position: "aboveBar",
        color: "#ff9800",
        shape: "circle",
        text: "假突破",
      }) as SeriesMarker<Time>,
  );
}

/** 从虚假流动性警报生成标记 */
function fakeLiquidityToMarkers(
  alerts: FakeLiquidityAlertData[],
): SeriesMarker<Time>[] {
  return alerts.map(
    (a) =>
      ({
        time: toUTCTimestamp(a.timestamp),
        position: "aboveBar",
        color: "#9c27b0",
        shape: "circle",
        text: "虚假流动性",
      }) as SeriesMarker<Time>,
  );
}

/** 从止损提示生成标记 */
function stopLossToMarkers(
  alerts: StopLossAlertData[],
): SeriesMarker<Time>[] {
  return alerts.map(
    (a) =>
      ({
        time: toUTCTimestamp(a.timestamp),
        position: "aboveBar",
        color: "#ef5350",
        shape: "square",
        text: "止损",
      }) as SeriesMarker<Time>,
  );
}

/** 从异常大单生成标记 */
function tickOutliersToMarkers(
  outliers: TickOutlierData[],
): SeriesMarker<Time>[] {
  return outliers.map(
    (o) =>
      ({
        time: toUTCTimestamp(o.timestamp),
        position: "belowBar",
        color: "#ff5722",
        shape: "circle",
        text: "异常大单",
      }) as SeriesMarker<Time>,
  );
}

// ==================== 组件实现 ====================

export function ScalpingChart({
  stockCode,
  height = DEFAULT_HEIGHT,
  managed = false,
}: ScalpingChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);

  const [chartReady, setChartReady] = useState(false);
  const [soundEnabled, setSoundEnabled] = useState(false);
  const [engineStatus, setEngineStatus] = useState<"idle" | "starting" | "running" | "error">("idle");

  // 从 useScalpingSocket 获取所有数据
  const {
    deltaData,
    pocData,
    priceLevels,
    signals,
    isConnected,
    trapAlerts,
    fakeBreakoutAlerts,
    fakeLiquidityAlerts,
    vwapExtension,
    vwapData,
    stopLossAlerts,
    tickOutliers,
  } = useScalpingSocket(stockCode);

  // 是否有实时数据流入
  const hasRealtimeData = deltaData.length > 0 || priceLevels.length > 0 || pocData !== null;

  // 当前价格：从 vwapExtension 或 0
  const currentPrice = vwapExtension?.current_price ?? 0;

  // ==================== 创建/销毁 chart 实例 ====================

  useEffect(() => {
    if (!containerRef.current) return;

    const chart = createChart(containerRef.current, {
      width: containerRef.current.clientWidth,
      height,
      ...CHART_OPTIONS,
    });

    const candleSeries = chart.addCandlestickSeries(CANDLE_OPTIONS);

    chartRef.current = chart;
    candleSeriesRef.current = candleSeries;
    setChartReady(true);

    // ResizeObserver 响应容器尺寸变化
    const observer = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (entry) {
        chart.applyOptions({ width: entry.contentRect.width });
      }
    });
    observer.observe(containerRef.current);

    return () => {
      observer.disconnect();
      setChartReady(false);
      chartRef.current = null;
      candleSeriesRef.current = null;
      // 延迟到下一帧再 remove chart，确保 lightweight-charts 内部
      // 已排队的 rAF paint 回调先执行完毕（Strict Mode 双重挂载场景下
      // cleanup 与 rAF 回调存在竞态，直接同步 remove 会导致
      // "Object is disposed" 错误）
      requestAnimationFrame(() => {
        try {
          chart.remove();
        } catch {
          // chart 可能已被销毁，静默处理
        }
      });
    };
  }, [height]);

  // ==================== 自动启动/停止后端 Scalping 引擎 ====================

  const prevStockRef = useRef<string | null>(null);

  useEffect(() => {
    // managed 模式：引擎由系统统一管理，但需确保该股票已在监控中
    if (managed) {
      if (!stockCode) return;
      let cancelled = false;
      const ensureMonitored = async () => {
        try {
          // 查询引擎状态，检查该股票是否已在监控中
          const statusRes = await fetch("/api/scalping/status");
          if (cancelled) return;
          const statusJson = await statusRes.json();
          const stocks = statusJson?.data?.stocks ?? {};
          if (stockCode in stocks) {
            setEngineStatus("running");
            return;
          }
          // 不在监控中，追加到引擎
          setEngineStatus("starting");
          const addRes = await fetch("/api/scalping/batch-add", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ stock_codes: [stockCode] }),
          });
          if (cancelled) return;
          const addJson = await addRes.json();
          setEngineStatus(addJson.success ? "running" : "error");
        } catch {
          if (!cancelled) setEngineStatus("error");
        }
      };
      ensureMonitored();
      return () => { cancelled = true; };
    }

    if (!stockCode) return;

    let cancelled = false;

    const startEngine = async () => {
      // 如果切换了股票，先停掉旧的
      const prev = prevStockRef.current;
      if (prev && prev !== stockCode) {
        try {
          await fetch("/api/scalping/stop", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ stock_codes: [prev] }),
          });
        } catch { /* ignore */ }
      }
      prevStockRef.current = stockCode;

      if (cancelled) return;
      setEngineStatus("starting");
      try {
        const res = await fetch("/api/scalping/start", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ stock_codes: [stockCode] }),
        });
        if (cancelled) return;
        const json = await res.json();
        setEngineStatus(json.success ? "running" : "error");
      } catch {
        if (!cancelled) setEngineStatus("error");
      }
    };
    startEngine();

    // 页面卸载时用 sendBeacon 停止引擎（不会被竞态影响）
    const handleUnload = () => {
      const blob = new Blob(
        [JSON.stringify({ stock_codes: [stockCode] })],
        { type: "application/json" },
      );
      navigator.sendBeacon("/api/scalping/stop", blob);
    };
    window.addEventListener("beforeunload", handleUnload);

    return () => {
      cancelled = true;
      window.removeEventListener("beforeunload", handleUnload);
      // 不在 cleanup 中发 stop 请求，避免刷新时竞态
      // 引擎会在下次 start 时自动处理（幂等），或页面关闭时通过 beacon 停止
    };
  }, [stockCode, managed]);

  // ==================== 合并所有标记并按时间排序 ====================

  const allMarkers = useMemo<SeriesMarker<Time>[]>(() => {
    const markers: SeriesMarker<Time>[] = [
      ...trapAlertsToMarkers(trapAlerts),
      ...fakeBreakoutToMarkers(fakeBreakoutAlerts),
      ...fakeLiquidityToMarkers(fakeLiquidityAlerts),
      ...stopLossToMarkers(stopLossAlerts),
      ...tickOutliersToMarkers(tickOutliers),
    ];
    return markers.sort((a, b) => (a.time as number) - (b.time as number));
  }, [
    trapAlerts,
    fakeBreakoutAlerts,
    fakeLiquidityAlerts,
    stopLossAlerts,
    tickOutliers,
  ]);

  // 设置标记到 candleSeries
  useEffect(() => {
    if (!candleSeriesRef.current || allMarkers.length === 0) return;
    try {
      candleSeriesRef.current.setMarkers(allMarkers);
    } catch {
      // 标记渲染失败时静默处理
    }
  }, [allMarkers]);

  // ==================== 从 deltaData 提取 OHLC 渲染蜡烛图 ====================

  useEffect(() => {
    if (!candleSeriesRef.current || deltaData.length === 0) return;

    // 过滤出包含 OHLC 数据的 delta 条目
    const candlePoints = deltaData
      .filter((d) => d.open != null && d.high != null && d.low != null && d.close != null)
      .map((d) => ({
        time: toUTCTimestamp(d.timestamp),
        open: d.open!,
        high: d.high!,
        low: d.low!,
        close: d.close!,
      }));

    if (candlePoints.length === 0) return;

    // TVLC 要求时间严格递增，去重保留最新
    const deduped = candlePoints.reduce<typeof candlePoints>((acc, cur) => {
      if (acc.length > 0 && acc[acc.length - 1].time >= cur.time) {
        acc[acc.length - 1] = cur;
      } else {
        acc.push(cur);
      }
      return acc;
    }, []);

    try {
      candleSeriesRef.current.setData(deduped);
    } catch {
      // 数据渲染失败时静默处理
    }
  }, [deltaData]);

  // ==================== 提示音开关回调 ====================

  const handleSoundToggle = useCallback((enabled: boolean) => {
    setSoundEnabled(enabled);
  }, []);

  // ==================== POC 数据解构 ====================

  const pocPrice = pocData?.poc_price ?? 0;
  const volumeProfile = useMemo<Record<number, number>>(() => {
    if (!pocData?.volume_profile) return {};
    const result: Record<number, number> = {};
    for (const [key, value] of Object.entries(pocData.volume_profile)) {
      result[Number(key)] = value;
    }
    return result;
  }, [pocData]);

  // ==================== 状态提示文案 ====================

  const statusMessage = useMemo(() => {
    if (managed && !hasRealtimeData)
      return "该股票未在 Scalping 监控中，请先启动引擎";
    if (engineStatus === "starting") return "正在启动 Scalping 引擎…";
    if (engineStatus === "error") return "Scalping 引擎启动失败";
    if (engineStatus === "running" && !hasRealtimeData)
      return "等待实时数据推送…（请确保开盘时间内）";
    // 数据累积提示
    if (engineStatus === "running" && deltaData.length > 0 && deltaData.length < 10) {
      const latestTime = deltaData[deltaData.length - 1]?.timestamp
        ? new Date(deltaData[deltaData.length - 1].timestamp).toLocaleTimeString("zh-CN", { hour12: false })
        : "";
      return `数据累积中... (${deltaData.length}/60) ${latestTime ? `最新: ${latestTime}` : ""}`;
    }
    return null;
  }, [managed, engineStatus, hasRealtimeData, deltaData]);

  // ==================== 渲染 ====================

  return (
    <div className="flex flex-col gap-2">
      {/* 顶部状态栏 */}
      <div className="flex items-center justify-between px-1">
        <div className="flex items-center gap-3">
          <span className="text-xs text-gray-400">
            Scalping · {stockCode}
          </span>
          {/* Delta 数据量显示 */}
          {deltaData.length > 0 && (
            <span className="text-xs text-gray-500">
              Delta: {deltaData.length} 条
            </span>
          )}
        </div>
        {/* 连接状态 + 引擎状态 */}
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1.5">
            <span
              className={`inline-block h-2 w-2 rounded-full ${engineStatus === "running"
                ? "bg-green-500"
                : engineStatus === "starting"
                  ? "bg-yellow-500 animate-pulse"
                  : engineStatus === "error"
                    ? "bg-red-500"
                    : "bg-gray-500"
                }`}
            />
            <span className="text-xs text-gray-500">
              {engineStatus === "running"
                ? "引擎运行中"
                : engineStatus === "starting"
                  ? "启动中"
                  : engineStatus === "error"
                    ? "启动失败"
                    : "未启动"}
            </span>
          </div>
          <div className="flex items-center gap-1.5">
            <span
              className={`inline-block h-2 w-2 rounded-full ${isConnected ? "bg-green-500" : "bg-red-500"
                }`}
            />
            <span className="text-xs text-gray-500">
              {isConnected ? "WS 已连接" : "WS 已断开"}
            </span>
          </div>
        </div>
      </div>

      {/* 图表区域 */}
      <div className="relative" style={{ height }}>
        <div ref={containerRef} className="h-full w-full" />

        {/* 状态提示浮层 */}
        {statusMessage && (
          <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
            <span className="rounded bg-black/60 px-4 py-2 text-sm text-gray-300">
              {statusMessage}
            </span>
          </div>
        )}

        {/* 子组件：chart 就绪后才渲染 */}
        {chartReady && chartRef.current && candleSeriesRef.current && (
          <>
            <DeltaHistogram
              chart={chartRef.current}
              deltaData={deltaData}
            />
            <PocOverlay
              chart={chartRef.current}
              series={candleSeriesRef.current}
              pocPrice={pocPrice}
              volumeProfile={volumeProfile}
            />
            <PriceLevelLines
              series={candleSeriesRef.current}
              levels={priceLevels}
            />
            <VwapOverlay
              chart={chartRef.current}
              series={candleSeriesRef.current}
              vwapData={vwapData}
              vwapExtension={vwapExtension}
              currentPrice={currentPrice}
            />
          </>
        )}
      </div>

      {/* 信号面板 */}
      <SignalPanel
        signals={signals}
        onSoundToggle={handleSoundToggle}
        soundEnabled={soundEnabled}
        vwapExtension={vwapExtension}
        stopLossAlerts={stopLossAlerts}
      />
    </div>
  );
}
