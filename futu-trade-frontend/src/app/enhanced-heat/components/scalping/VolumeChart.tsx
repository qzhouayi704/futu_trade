/**
 * VolumeChart - 成交量柱图 + 大单流向分离
 *
 * 使用 TVLC HistogramSeries 渲染：
 * - 普通成交量柱：涨绿跌红（与蜡烛同色）
 * - 大单高亮：big_order_volume 超阈值时用亮色标记
 * - 大单流向分离模式：big_buy_volume（绿）和 big_sell_volume（红）叠加
 */

"use client";

import { useEffect, useRef } from "react";
import type { IChartApi, ISeriesApi, UTCTimestamp } from "lightweight-charts";
import type { DeltaUpdateData } from "@/types/scalping";

// ==================== 组件接口 ====================

export interface VolumeChartProps {
  chart: IChartApi;
  deltaData: DeltaUpdateData[];
  /** 是否启用大单流向分离模式 */
  showBigOrderFlow?: boolean;
}

// ==================== 颜色常量 ====================

const COLOR_VOL_UP = "rgba(38, 166, 154, 0.5)";
const COLOR_VOL_DOWN = "rgba(239, 83, 80, 0.5)";
const COLOR_VOL_UP_BIG = "rgba(0, 230, 118, 0.8)";
const COLOR_VOL_DOWN_BIG = "rgba(255, 23, 68, 0.8)";

/** 大单流向分离模式颜色 */
const COLOR_BIG_BUY = "#26a69a";
const COLOR_BIG_SELL = "#ef5350";

// ==================== 大单检测参数 ====================

const BIG_ORDER_LOOKBACK = 20;
const BIG_ORDER_MULTIPLIER = 2;

// ==================== 工具函数 ====================

function toUTCTimestamp(isoTimestamp: string): UTCTimestamp {
  return Math.floor(new Date(isoTimestamp).getTime() / 1000) as UTCTimestamp;
}

/** 判断是否为大单异常量 */
function isBigVolume(
  currentIndex: number,
  deltaData: DeltaUpdateData[],
): boolean {
  const start = Math.max(0, currentIndex - BIG_ORDER_LOOKBACK);
  const end = currentIndex;
  if (start >= end) return false;

  let sum = 0;
  for (let i = start; i < end; i++) {
    sum += deltaData[i].volume;
  }
  const avg = sum / (end - start);
  if (avg === 0) return false;

  return deltaData[currentIndex].volume > avg * BIG_ORDER_MULTIPLIER;
}

/** 去重并保留最新值（TVLC 要求时间严格递增） */
function dedupeByTime<T extends { time: UTCTimestamp }>(data: T[]): T[] {
  return data.reduce<T[]>((acc, cur) => {
    if (acc.length > 0 && acc[acc.length - 1].time >= cur.time) {
      acc[acc.length - 1] = cur;
    } else {
      acc.push(cur);
    }
    return acc;
  }, []);
}

// ==================== 组件实现 ====================

export function VolumeChart({
  chart,
  deltaData,
  showBigOrderFlow = false,
}: VolumeChartProps) {
  const volSeriesRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const bigBuySeriesRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const bigSellSeriesRef = useRef<ISeriesApi<"Histogram"> | null>(null);

  // 创建/销毁 series
  useEffect(() => {
    const volSeries = chart.addHistogramSeries({
      priceFormat: { type: "volume" },
      priceScaleId: "vol",
    });
    chart.priceScale("vol").applyOptions({
      scaleMargins: { top: 0.1, bottom: 0.05 },
    });

    volSeriesRef.current = volSeries;

    // 大单流向分离模式的两个 series
    if (showBigOrderFlow) {
      const buySeries = chart.addHistogramSeries({
        priceFormat: { type: "volume" },
        priceScaleId: "bigflow",
      });
      const sellSeries = chart.addHistogramSeries({
        priceFormat: { type: "volume" },
        priceScaleId: "bigflow",
      });
      chart.priceScale("bigflow").applyOptions({
        scaleMargins: { top: 0.6, bottom: 0.05 },
      });
      bigBuySeriesRef.current = buySeries;
      bigSellSeriesRef.current = sellSeries;
    }

    return () => {
      try { chart.removeSeries(volSeries); } catch { /* disposed */ }
      if (bigBuySeriesRef.current) {
        try { chart.removeSeries(bigBuySeriesRef.current); } catch { /* disposed */ }
      }
      if (bigSellSeriesRef.current) {
        try { chart.removeSeries(bigSellSeriesRef.current); } catch { /* disposed */ }
      }
      volSeriesRef.current = null;
      bigBuySeriesRef.current = null;
      bigSellSeriesRef.current = null;
    };
  }, [chart, showBigOrderFlow]);

  // 数据更新
  useEffect(() => {
    if (!volSeriesRef.current || deltaData.length === 0) return;

    // 成交量柱
    const volData = deltaData.map((item, index) => {
      const isUp = (item.close ?? 0) >= (item.open ?? 0);
      const big = isBigVolume(index, deltaData);
      return {
        time: toUTCTimestamp(item.timestamp),
        value: item.volume,
        color: big
          ? (isUp ? COLOR_VOL_UP_BIG : COLOR_VOL_DOWN_BIG)
          : (isUp ? COLOR_VOL_UP : COLOR_VOL_DOWN),
      };
    });

    volSeriesRef.current.setData(dedupeByTime(volData));

    // 大单流向分离
    if (showBigOrderFlow && bigBuySeriesRef.current && bigSellSeriesRef.current) {
      const buyData = deltaData
        .filter((d) => d.big_buy_volume != null && d.big_buy_volume > 0)
        .map((d) => ({
          time: toUTCTimestamp(d.timestamp),
          value: d.big_buy_volume!,
          color: COLOR_BIG_BUY,
        }));

      const sellData = deltaData
        .filter((d) => d.big_sell_volume != null && d.big_sell_volume > 0)
        .map((d) => ({
          time: toUTCTimestamp(d.timestamp),
          value: -d.big_sell_volume!, // 负值向下
          color: COLOR_BIG_SELL,
        }));

      bigBuySeriesRef.current.setData(dedupeByTime(buyData));
      bigSellSeriesRef.current.setData(dedupeByTime(sellData));
    }

    // 数据较少时自动适配
    if (deltaData.length < 20) {
      chart.timeScale().fitContent();
    }
  }, [deltaData, showBigOrderFlow, chart]);

  return null;
}
