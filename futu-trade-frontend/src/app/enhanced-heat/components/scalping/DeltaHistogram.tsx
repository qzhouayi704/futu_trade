/**
 * DeltaHistogram - Delta 动量柱图组件
 *
 * 使用 TVLC HistogramSeries 渲染多空净动量柱图：
 * - Delta > 0 → 绿色（买方主导）
 * - Delta < 0 → 红色（卖方主导）
 * - 极值柱（|delta| > 近 20 周期均值 × 2）→ 更亮的颜色高亮
 *
 * 需求引用: 7.1, 7.2, 7.3, 7.4, 7.5
 */

"use client";

import { useEffect, useRef } from "react";
import type { IChartApi, ISeriesApi, UTCTimestamp } from "lightweight-charts";
import type { DeltaUpdateData } from "@/types/scalping";

// ==================== 组件接口 ====================

export interface DeltaHistogramProps {
  chart: IChartApi;
  deltaData: DeltaUpdateData[];
}

// ==================== 颜色常量 ====================

/** 正常正值（买方）绿色 */
const COLOR_POSITIVE = "#26a69a";
/** 正常负值（卖方）红色 */
const COLOR_NEGATIVE = "#ef5350";
/** 极值正柱 - 更亮的绿色 */
const COLOR_EXTREME_POSITIVE = "#00e676";
/** 极值负柱 - 更亮的红色 */
const COLOR_EXTREME_NEGATIVE = "#ff1744";

// ==================== 极值检测参数 ====================

/** 极值检测回溯周期数 */
const EXTREME_LOOKBACK = 20;
/** 极值倍数阈值 */
const EXTREME_MULTIPLIER = 2;

// ==================== 工具函数 ====================

/** ISO 时间戳转 TVLC UTCTimestamp（Unix 秒） */
function toUTCTimestamp(isoTimestamp: string): UTCTimestamp {
  return Math.floor(new Date(isoTimestamp).getTime() / 1000) as UTCTimestamp;
}

/**
 * 判断当前 delta 是否为极值柱
 *
 * 计算最近 lookback 个周期的 |delta| 均值，
 * 当前 |delta| 超过该均值 × multiplier 时为极值。
 */
function isExtremeDelta(
  currentIndex: number,
  deltaData: DeltaUpdateData[],
  lookback: number = EXTREME_LOOKBACK,
  multiplier: number = EXTREME_MULTIPLIER,
): boolean {
  // 回溯范围：当前索引之前的 lookback 个周期
  const start = Math.max(0, currentIndex - lookback);
  const end = currentIndex;

  if (start >= end) return false;

  let sum = 0;
  for (let i = start; i < end; i++) {
    sum += Math.abs(deltaData[i].delta);
  }
  const avg = sum / (end - start);

  // 均值为 0 时不标记极值（避免除零和无意义判定）
  if (avg === 0) return false;

  return Math.abs(deltaData[currentIndex].delta) > avg * multiplier;
}

/** 根据 delta 值和是否极值确定柱体颜色 */
export function getDeltaColor(delta: number, extreme: boolean): string {
  if (delta > 0) {
    return extreme ? COLOR_EXTREME_POSITIVE : COLOR_POSITIVE;
  }
  return extreme ? COLOR_EXTREME_NEGATIVE : COLOR_NEGATIVE;
}

// ==================== 组件实现 ====================

export function DeltaHistogram({ chart, deltaData }: DeltaHistogramProps) {
  const seriesRef = useRef<ISeriesApi<"Histogram"> | null>(null);

  // 创建和销毁 HistogramSeries
  useEffect(() => {
    const series = chart.addHistogramSeries({
      priceFormat: {
        type: "price",
        precision: 0,
        minMove: 1,
      },
      priceScaleId: "delta",
    });

    // Y 轴配置：底部区域显示，显示净动量数值
    series.priceScale().applyOptions({
      scaleMargins: {
        top: 0.8,
        bottom: 0,
      },
    });

    seriesRef.current = series;

    return () => {
      try {
        chart.removeSeries(series);
      } catch {
        // 图表可能已销毁，静默处理
      }
      seriesRef.current = null;
    };
  }, [chart]);

  // 数据更新时重新渲染柱图
  useEffect(() => {
    if (!seriesRef.current || deltaData.length === 0) return;

    const histogramData = deltaData.map((item, index) => ({
      time: toUTCTimestamp(item.timestamp),
      value: item.delta,
      color: getDeltaColor(
        item.delta,
        isExtremeDelta(index, deltaData),
      ),
    }));

    // TVLC 要求时间严格递增，去重并保留最新值
    const deduped = histogramData.reduce<typeof histogramData>((acc, cur) => {
      if (acc.length > 0 && acc[acc.length - 1].time >= cur.time) {
        acc[acc.length - 1] = cur; // 同一秒内用最新值覆盖
      } else {
        acc.push(cur);
      }
      return acc;
    }, []);

    seriesRef.current.setData(deduped);
  }, [deltaData]);

  // 纯数据驱动组件，不渲染 DOM
  return null;
}
