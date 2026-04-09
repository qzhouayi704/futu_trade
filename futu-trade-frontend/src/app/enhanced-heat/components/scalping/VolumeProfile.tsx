/**
 * VolumeProfile - 价位成交量分布侧边柱
 *
 * 利用 pocData.volume_profile 在价格图右侧渲染水平柱状图：
 * - POC 价位（最高成交量）用亮色高亮
 * - 其余价位按成交量比例渲染
 * - 使用 CSS 绝对定位叠加在价格图右侧
 */

"use client";

import { useEffect, useState, useCallback } from "react";
import type { ISeriesApi, IChartApi } from "lightweight-charts";
import type { PocUpdateData } from "@/types/scalping";

// ==================== 组件接口 ====================

export interface VolumeProfileProps {
  chart: IChartApi;
  series: ISeriesApi<"Candlestick">;
  pocData: PocUpdateData | null;
}

// ==================== 颜色常量 ====================

const COLOR_POC = "#FFD700";
const COLOR_ABOVE_POC = "rgba(38, 166, 154, 0.6)";
const COLOR_BELOW_POC = "rgba(239, 83, 80, 0.6)";
const BAR_MAX_WIDTH = 80; // px

// ==================== 组件实现 ====================

interface ProfileBar {
  price: number;
  volume: number;
  y: number;
  width: number;
  color: string;
}

export function VolumeProfile({ chart, series, pocData }: VolumeProfileProps) {
  const [bars, setBars] = useState<ProfileBar[]>([]);

  const recalculate = useCallback(() => {
    if (!pocData || !pocData.volume_profile) {
      setBars([]);
      return;
    }

    const entries = Object.entries(pocData.volume_profile)
      .map(([priceStr, vol]) => ({ price: parseFloat(priceStr), volume: vol }))
      .filter((e) => !isNaN(e.price) && e.volume > 0);

    if (entries.length === 0) {
      setBars([]);
      return;
    }

    const maxVol = Math.max(...entries.map((e) => e.volume));
    const pocPrice = pocData.poc_price;

    const newBars: ProfileBar[] = [];
    for (const entry of entries) {
      const y = series.priceToCoordinate(entry.price);
      if (y === null) continue;

      const widthRatio = entry.volume / maxVol;
      const isPoc = Math.abs(entry.price - pocPrice) < 0.01;
      const isAbove = entry.price > pocPrice;

      newBars.push({
        price: entry.price,
        volume: entry.volume,
        y: y as number,
        width: Math.max(2, widthRatio * BAR_MAX_WIDTH),
        color: isPoc ? COLOR_POC : isAbove ? COLOR_ABOVE_POC : COLOR_BELOW_POC,
      });
    }

    setBars(newBars);
  }, [series, pocData]);

  // 监听图表缩放/滚动
  useEffect(() => {
    recalculate();
    const ts = chart.timeScale();
    ts.subscribeVisibleLogicalRangeChange(recalculate);
    return () => {
      ts.unsubscribeVisibleLogicalRangeChange(recalculate);
    };
  }, [chart, recalculate]);

  // 数据变化时重新计算
  useEffect(() => {
    recalculate();
  }, [pocData, recalculate]);

  if (bars.length === 0) return null;

  return (
    <div
      style={{
        position: "absolute",
        top: 0,
        right: 50, // 留出 Y 轴标签空间
        bottom: 0,
        width: BAR_MAX_WIDTH,
        pointerEvents: "none",
        overflow: "hidden",
      }}
    >
      {bars.map((bar) => (
        <div
          key={bar.price}
          style={{
            position: "absolute",
            right: 0,
            top: bar.y - 1,
            height: 2,
            width: bar.width,
            backgroundColor: bar.color,
            borderRadius: "1px 0 0 1px",
            opacity: 0.8,
          }}
        />
      ))}
    </div>
  );
}
