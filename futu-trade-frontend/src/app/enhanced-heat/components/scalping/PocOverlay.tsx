/**
 * PocOverlay - POC 叠加层 + 成交量分布条形图
 *
 * 使用 HTML/CSS 绝对定位叠加在 TVLC Canvas 上：
 * - 横向成交量分布条形图（从右侧向左延伸，半透明蓝色）
 * - POC 金色实线（价格变化时平滑过渡）
 * - 监听图表缩放/滚动事件同步更新位置
 *
 * 需求引用: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6
 */

"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import type { IChartApi, ISeriesApi } from "lightweight-charts";

// ==================== 组件接口 ====================

export interface PocOverlayProps {
  chart: IChartApi;
  series: ISeriesApi<"Candlestick">;
  pocPrice: number;
  volumeProfile: Record<number, number>;
}

// ==================== 样式常量 ====================

/** POC 金色实线颜色 */
const POC_COLOR = "#FFD700";
/** POC 线宽度 */
const POC_LINE_WIDTH = 2;
/** 成交量分布条颜色（半透明蓝色） */
const VOLUME_BAR_COLOR = "rgba(33, 150, 243, 0.3)";
/** 成交量分布条最大宽度占容器宽度的比例 */
const MAX_WIDTH_RATIO = 0.3;
/** POC 线平滑过渡时间（毫秒） */
const POC_TRANSITION_MS = 300;
/** 成交量分布条最小高度（像素） */
const MIN_BAR_HEIGHT = 1;

// ==================== 工具函数 ====================

/**
 * 计算单个成交量分布条的宽度
 *
 * Property 11: 成交量分布条宽度比例
 * 每个价位条的宽度 = (该档位成交量 / 最大档位成交量) × 最大宽度
 * 最大档位的条宽度 = 最大宽度
 *
 * @param volume - 该档位成交量
 * @param maxVolume - 最大档位成交量
 * @param maxWidth - 最大宽度（像素）
 * @returns 条形宽度（像素），maxVolume <= 0 时返回 0
 */
export function calculateBarWidth(
  volume: number,
  maxVolume: number,
  maxWidth: number,
): number {
  if (maxVolume <= 0 || maxWidth <= 0 || volume <= 0) return 0;
  return (volume / maxVolume) * maxWidth;
}

/**
 * 将 volumeProfile 的 key 统一转为数字
 * PocUpdateData 中 volume_profile 的 key 是 string（JSON 限制），
 * 组件 props 中是 number，此函数兼容两种情况。
 */
function normalizeVolumeProfile(
  profile: Record<string | number, number>,
): Map<number, number> {
  const result = new Map<number, number>();
  for (const [key, value] of Object.entries(profile)) {
    const price = Number(key);
    if (!isNaN(price) && value > 0) {
      result.set(price, value);
    }
  }
  return result;
}

// ==================== 内部类型 ====================

interface BarRenderData {
  price: number;
  y: number;
  width: number;
  height: number;
  isPoc: boolean;
}

// ==================== 组件实现 ====================

export function PocOverlay({
  chart,
  series,
  pocPrice,
  volumeProfile,
}: PocOverlayProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [bars, setBars] = useState<BarRenderData[]>([]);
  const [pocY, setPocY] = useState<number | null>(null);
  const [containerWidth, setContainerWidth] = useState(0);

  /**
   * 重新计算所有条形的 Y 坐标和尺寸
   * 在图表缩放/滚动或数据变化时调用
   */
  const recalculate = useCallback(() => {
    if (!containerRef.current) return;

    const rect = containerRef.current.getBoundingClientRect();
    const width = rect.width;
    setContainerWidth(width);

    const maxBarWidth = width * MAX_WIDTH_RATIO;
    const normalized = normalizeVolumeProfile(volumeProfile);

    if (normalized.size === 0) {
      setBars([]);
      setPocY(null);
      return;
    }

    // 找到最大成交量
    let maxVolume = 0;
    for (const vol of normalized.values()) {
      if (vol > maxVolume) maxVolume = vol;
    }

    // 获取所有价格并排序，用于计算条形高度
    const prices = Array.from(normalized.keys()).sort((a, b) => a - b);

    // 计算价格间距（用于条形高度）
    let priceStep = 0;
    if (prices.length >= 2) {
      // 使用最小价格间距作为条形高度基准
      let minGap = Infinity;
      for (let i = 1; i < prices.length; i++) {
        const gap = prices[i] - prices[i - 1];
        if (gap > 0 && gap < minGap) minGap = gap;
      }
      priceStep = minGap === Infinity ? 0 : minGap;
    }

    // 计算每个条形的渲染数据
    const newBars: BarRenderData[] = [];

    for (const [price, volume] of normalized) {
      const y = series.priceToCoordinate(price);
      if (y === null) continue;

      // 计算条形高度：基于价格间距的像素差
      let barHeight = MIN_BAR_HEIGHT;
      if (priceStep > 0) {
        const yTop = series.priceToCoordinate(price + priceStep / 2);
        const yBottom = series.priceToCoordinate(price - priceStep / 2);
        if (yTop !== null && yBottom !== null) {
          barHeight = Math.max(Math.abs(yBottom - yTop), MIN_BAR_HEIGHT);
        }
      }

      const barWidth = calculateBarWidth(volume, maxVolume, maxBarWidth);

      newBars.push({
        price,
        y: y as number,
        width: barWidth,
        height: barHeight,
        isPoc: price === pocPrice,
      });
    }

    setBars(newBars);

    // 计算 POC 线 Y 坐标
    const pocCoord = series.priceToCoordinate(pocPrice);
    setPocY(pocCoord !== null ? (pocCoord as number) : null);
  }, [series, pocPrice, volumeProfile]);

  // 初始计算 + 监听图表缩放/滚动事件
  useEffect(() => {
    recalculate();

    const timeScale = chart.timeScale();
    timeScale.subscribeVisibleLogicalRangeChange(recalculate);

    return () => {
      timeScale.unsubscribeVisibleLogicalRangeChange(recalculate);
    };
  }, [chart, recalculate]);

  // 数据变化时重新计算
  useEffect(() => {
    recalculate();
  }, [pocPrice, volumeProfile, recalculate]);

  // 监听容器尺寸变化
  useEffect(() => {
    if (!containerRef.current) return;

    const observer = new ResizeObserver(() => {
      recalculate();
    });
    observer.observe(containerRef.current);

    return () => {
      observer.disconnect();
    };
  }, [recalculate]);

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
      {/* 成交量分布条形图 */}
      {bars.map((bar) => (
        <div
          key={bar.price}
          style={{
            position: "absolute",
            right: 0,
            top: bar.y - bar.height / 2,
            width: bar.width,
            height: bar.height,
            backgroundColor: VOLUME_BAR_COLOR,
          }}
        />
      ))}

      {/* POC 金色实线 */}
      {pocY !== null && (
        <div
          style={{
            position: "absolute",
            left: 0,
            right: 0,
            top: pocY - POC_LINE_WIDTH / 2,
            height: POC_LINE_WIDTH,
            backgroundColor: POC_COLOR,
            transition: `top ${POC_TRANSITION_MS}ms ease-in-out`,
            zIndex: 1,
          }}
        />
      )}
    </div>
  );
}
