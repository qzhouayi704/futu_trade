/**
 * VwapOverlay - VWAP 线 + 偏离警示带
 *
 * 使用 TVLC LineSeries 渲染蓝色虚线 VWAP 线：
 * - 实时更新 VWAP 线数据点
 * - 偏离超限时在 VWAP 线与当前价格之间渲染半透明红色警示带
 * - 使用 HTML/CSS 绝对定位叠加警示带（与 PocOverlay 模式一致）
 * - 偏离恢复正常时移除警示带
 * - 监听图表缩放/滚动事件同步更新位置
 *
 * 需求引用: 16.7
 */

"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { LineStyle } from "lightweight-charts";
import type {
  IChartApi,
  ISeriesApi,
  UTCTimestamp,
} from "lightweight-charts";
import type { VwapExtensionAlertData } from "@/types/scalping";

// ==================== 组件接口 ====================

export interface VwapOverlayProps {
  chart: IChartApi;
  series: ISeriesApi<"Candlestick">;
  vwapData: { vwap: number; timestamp: string } | null;
  vwapExtension: VwapExtensionAlertData | null;
  currentPrice: number;
}

// ==================== 样式常量 ====================

/** VWAP 线颜色（蓝色） */
const VWAP_LINE_COLOR = "#2196F3";
/** VWAP 线宽度 */
const VWAP_LINE_WIDTH = 2;
/** 偏离警示带颜色（半透明红色） */
const ALERT_BAND_COLOR = "rgba(239, 83, 80, 0.15)";

// ==================== 工具函数 ====================

/** ISO 时间戳转 TVLC UTCTimestamp（Unix 秒） */
function toUTCTimestamp(isoTimestamp: string): UTCTimestamp {
  return Math.floor(new Date(isoTimestamp).getTime() / 1000) as UTCTimestamp;
}

// ==================== 组件实现 ====================

export function VwapOverlay({
  chart,
  series,
  vwapData,
  vwapExtension,
  currentPrice,
}: VwapOverlayProps) {
  const lineSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [bandStyle, setBandStyle] = useState<{
    top: number;
    height: number;
  } | null>(null);

  // ==================== 创建/销毁 LineSeries ====================

  useEffect(() => {
    const lineSeries = chart.addLineSeries({
      color: VWAP_LINE_COLOR,
      lineWidth: VWAP_LINE_WIDTH,
      lineStyle: LineStyle.Dashed,
      priceScaleId: "right",
      lastValueVisible: true,
      title: "VWAP",
    });

    lineSeriesRef.current = lineSeries;

    return () => {
      try {
        chart.removeSeries(lineSeries);
      } catch {
        // 图表可能已销毁，静默处理
      }
      lineSeriesRef.current = null;
    };
  }, [chart]);

  // ==================== 更新 VWAP 线数据点 ====================

  useEffect(() => {
    if (!lineSeriesRef.current || !vwapData) return;

    try {
      lineSeriesRef.current.update({
        time: toUTCTimestamp(vwapData.timestamp),
        value: vwapData.vwap,
      });
    } catch {
      // 数据格式异常时静默处理
    }
  }, [vwapData]);

  // ==================== 计算警示带位置 ====================

  const recalculateBand = useCallback(() => {
    // 无偏离超限时不显示警示带
    if (!vwapExtension) {
      setBandStyle(null);
      return;
    }

    const vwapY = series.priceToCoordinate(vwapExtension.vwap_value);
    const priceY = series.priceToCoordinate(currentPrice);

    // priceToCoordinate 返回 null 时隐藏警示带
    if (vwapY === null || priceY === null) {
      setBandStyle(null);
      return;
    }

    const y1 = vwapY as number;
    const y2 = priceY as number;
    const top = Math.min(y1, y2);
    const height = Math.abs(y2 - y1);

    // 高度过小时不渲染
    if (height < 1) {
      setBandStyle(null);
      return;
    }

    setBandStyle({ top, height });
  }, [series, vwapExtension, currentPrice]);

  // ==================== 监听图表缩放/滚动事件 ====================

  useEffect(() => {
    recalculateBand();

    const timeScale = chart.timeScale();
    timeScale.subscribeVisibleLogicalRangeChange(recalculateBand);

    return () => {
      timeScale.unsubscribeVisibleLogicalRangeChange(recalculateBand);
    };
  }, [chart, recalculateBand]);

  // 数据变化时重新计算
  useEffect(() => {
    recalculateBand();
  }, [vwapExtension, currentPrice, recalculateBand]);

  // ==================== 渲染警示带 ====================

  // 无偏离超限时不渲染 DOM
  if (!bandStyle) return null;

  return (
    <div
      ref={containerRef}
      style={{
        position: "absolute",
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        pointerEvents: "none",
        overflow: "hidden",
      }}
    >
      <div
        style={{
          position: "absolute",
          left: 0,
          right: 0,
          top: bandStyle.top,
          height: bandStyle.height,
          backgroundColor: ALERT_BAND_COLOR,
        }}
      />
    </div>
  );
}
