/**
 * PriceLevelLines - 动态阻力/支撑线组件
 *
 * 使用 TVLC series.createPriceLine() 渲染水平价格线：
 * - 阻力线（resistance）→ 红色 (#ef5350)
 * - 支撑线（support）→ 绿色 (#26a69a)
 * - levels 数组变化时同步 price lines（新增 → createPriceLine，移除 → removePriceLine）
 * - 每条线旁显示挂单存量标签（通过 title 属性）
 * - 组件卸载时清理所有 price lines
 *
 * 纯数据驱动组件，return null。
 * levels 数组由 useScalpingSocket 管理，只包含当前有效的 levels。
 *
 * 需求引用: 6.1, 6.2, 6.3, 6.4, 6.5
 */

"use client";

import { useEffect, useRef } from "react";
import { LineStyle } from "lightweight-charts";
import type { ISeriesApi, IPriceLine } from "lightweight-charts";
import type { PriceLevelData } from "@/types/scalping";

// ==================== 组件接口 ====================

export interface PriceLevelLinesProps {
  series: ISeriesApi<"Candlestick">;
  levels: PriceLevelData[];
}

// ==================== 颜色常量 ====================

/** 阻力线颜色（红色） */
const COLOR_RESISTANCE = "#ef5350";
/** 支撑线颜色（绿色） */
const COLOR_SUPPORT = "#26a69a";
/** 价格线宽度 */
const LINE_WIDTH = 2;

// ==================== 工具函数 ====================

/**
 * 将成交量格式化为千分位字符串
 *
 * @example formatVolume(1234) → "1,234"
 * @example formatVolume(1234567) → "1,234,567"
 */
export function formatVolume(volume: number): string {
  return volume.toLocaleString("en-US");
}

/**
 * 生成价格线的 title 标签
 *
 * 阻力线 → "阻力 {volume}"
 * 支撑线 → "支撑 {volume}"
 */
export function buildTitle(side: PriceLevelData["side"], volume: number): string {
  const prefix = side === "resistance" ? "阻力" : "支撑";
  return `${prefix} ${formatVolume(volume)}`;
}

/**
 * 根据 side 返回对应颜色
 */
function getLineColor(side: PriceLevelData["side"]): string {
  return side === "resistance" ? COLOR_RESISTANCE : COLOR_SUPPORT;
}

// ==================== 组件实现 ====================

export function PriceLevelLines({ series, levels }: PriceLevelLinesProps) {
  /** Map<price, IPriceLine> 跟踪已创建的 price lines */
  const linesRef = useRef<Map<number, IPriceLine>>(new Map());

  // levels 变化时同步 price lines
  useEffect(() => {
    const currentLines = linesRef.current;

    // 构建当前 levels 的 price 集合，用于快速查找
    const activePrices = new Set<number>();

    for (const level of levels) {
      activePrices.add(level.price);

      if (currentLines.has(level.price)) {
        // 已存在的线 → 移除旧线并重新创建（volume 可能变化）
        const existingLine = currentLines.get(level.price)!;
        try {
          series.removePriceLine(existingLine);
        } catch {
          // series 可能已销毁，静默处理
        }
        currentLines.delete(level.price);
      }

      // 创建新的 price line
      try {
        const priceLine = series.createPriceLine({
          price: level.price,
          color: getLineColor(level.side),
          lineWidth: LINE_WIDTH,
          lineStyle: LineStyle.Solid,
          axisLabelVisible: true,
          title: buildTitle(level.side, level.volume),
        });
        currentLines.set(level.price, priceLine);
      } catch {
        // createPriceLine 失败时静默处理，不影响其他线
      }
    }

    // 移除不再存在于 levels 中的旧线
    for (const [price, priceLine] of currentLines) {
      if (!activePrices.has(price)) {
        try {
          series.removePriceLine(priceLine);
        } catch {
          // series 可能已销毁，静默处理
        }
        currentLines.delete(price);
      }
    }
  }, [series, levels]);

  // 组件卸载时清理所有 price lines
  useEffect(() => {
    return () => {
      const currentLines = linesRef.current;
      for (const [price, priceLine] of currentLines) {
        try {
          series.removePriceLine(priceLine);
        } catch {
          // series 可能已销毁，静默处理
        }
      }
      currentLines.clear();
    };
  }, [series]);

  // 纯数据驱动组件，不渲染 DOM
  return null;
}
