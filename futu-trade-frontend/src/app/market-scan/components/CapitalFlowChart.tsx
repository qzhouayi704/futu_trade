// 主力 vs 散户资金流走势图
// 用 lightweight-charts 绘制双线面积图

"use client";

import { useEffect, useRef } from "react";
import type { CapitalFlowTimelinePoint } from "@/lib/api/enhanced-heat";

interface CapitalFlowChartProps {
  data: CapitalFlowTimelinePoint[];
  height?: number;
}

export function CapitalFlowChart({ data, height = 380 }: CapitalFlowChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<ReturnType<typeof import("lightweight-charts").createChart> | null>(null);

  useEffect(() => {
    if (!containerRef.current || data.length === 0) return;

    let disposed = false;

    import("lightweight-charts").then(({ createChart, LineType, CrosshairMode }) => {
      if (disposed || !containerRef.current) return;

      // 清理旧图表
      if (chartRef.current) {
        chartRef.current.remove();
        chartRef.current = null;
      }

      const chart = createChart(containerRef.current, {
        width: containerRef.current.clientWidth,
        height,
        layout: {
          background: { color: "#fafafa" },
          textColor: "#6b7280",
          fontSize: 11,
        },
        grid: {
          vertLines: { color: "#f3f4f6" },
          horzLines: { color: "#f3f4f6" },
        },
        crosshair: {
          mode: CrosshairMode.Magnet,
        },
        rightPriceScale: {
          borderColor: "#e5e7eb",
        },
        timeScale: {
          borderColor: "#e5e7eb",
          timeVisible: true,
          secondsVisible: false,
        },
      });

      chartRef.current = chart;

      // === 资金流系列：全部放到 left 轴 ===

      // 主力净流入（红色区域线）
      const mainSeries = chart.addAreaSeries({
        topColor: "rgba(239, 68, 68, 0.3)",
        bottomColor: "rgba(239, 68, 68, 0.02)",
        lineColor: "#ef4444",
        lineWidth: 2,
        title: "主力",
        priceScaleId: "left",
      });

      // 散户净流入（绿色区域线）
      const retailSeries = chart.addAreaSeries({
        topColor: "rgba(34, 197, 94, 0.25)",
        bottomColor: "rgba(34, 197, 94, 0.02)",
        lineColor: "#22c55e",
        lineWidth: 2,
        title: "散户",
        priceScaleId: "left",
      });

      // 零轴基线
      const zeroSeries = chart.addLineSeries({
        color: "#9ca3af",
        lineWidth: 1,
        lineStyle: 2, // Dashed
        title: "",
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: false,
        priceScaleId: "left",
      });

      // 将 HH:MM 转为 Unix 时间戳，补偿时区（lightweight-charts 按 UTC 显示）
      const today = new Date();
      const tzOffsetSec = today.getTimezoneOffset() * 60; // 本地 vs UTC 偏移（秒）
      const toTimestamp = (hhmm: string) => {
        const [h, m] = hhmm.split(':').map(Number);
        const d = new Date(today.getFullYear(), today.getMonth(), today.getDate(), h || 0, m || 0);
        return Math.floor(d.getTime() / 1000 - tzOffsetSec) as unknown as import("lightweight-charts").Time;
      };

      const mainData = data.map((p) => ({
        time: toTimestamp(p.time),
        value: p.main_in,
      }));

      const retailData = data.map((p) => ({
        time: toTimestamp(p.time),
        value: p.retail_in,
      }));

      const zeroData = data.map((p) => ({
        time: toTimestamp(p.time),
        value: 0,
      }));

      mainSeries.setData(mainData);
      retailSeries.setData(retailData);
      zeroSeries.setData(zeroData);

      // 大单强度线（橙色，独立 strength 轴，范围 -1 ~ +1）
      const strengthPoints = data.filter(p => p.strength != null);
      if (strengthPoints.length > 3) {
        const strengthSeries = chart.addLineSeries({
          color: "#f97316",
          lineWidth: 2,
          lineStyle: 0,
          title: "强度",
          priceScaleId: "strength",
          lastValueVisible: true,
          priceLineVisible: false,
          crosshairMarkerRadius: 4,
        });

        // 强度零轴
        const strZeroSeries = chart.addLineSeries({
          color: "#f9731640",
          lineWidth: 1,
          lineStyle: 2,
          title: "",
          priceScaleId: "strength",
          priceLineVisible: false,
          lastValueVisible: false,
          crosshairMarkerVisible: false,
        });

        strengthSeries.setData(strengthPoints.map(p => ({
          time: toTimestamp(p.time),
          value: p.strength!,
        })));
        strZeroSeries.setData(strengthPoints.map(p => ({
          time: toTimestamp(p.time),
          value: 0,
        })));

        // 配置 strength 轴（不可见，但独立缩放）
        chart.priceScale("strength").applyOptions({
          scaleMargins: { top: 0.05, bottom: 0.05 },
          visible: false,
        });
      }

      // === 股价走势线：使用默认 right 轴（独立缩放） ===
      const pricePoints = data.filter(p => p.price != null && p.price > 0);
      if (pricePoints.length > 10) {
        const priceSeries = chart.addLineSeries({
          color: "#7c3aed",
          lineWidth: 2,
          lineStyle: 0,
          title: "股价",
          priceScaleId: "right",  // 默认右轴
          lastValueVisible: true,
          priceLineVisible: true,
          priceLineColor: "#7c3aed",
          priceLineStyle: 2,
        });

        // 配置左轴（资金流）
        chart.priceScale("left").applyOptions({
          scaleMargins: { top: 0.08, bottom: 0.08 },
          visible: true,
          borderColor: "#d1d5db",
        });

        // 配置右轴（股价��
        chart.priceScale("right").applyOptions({
          scaleMargins: { top: 0.08, bottom: 0.08 },
          visible: true,
          borderColor: "#7c3aed",
        });

        const priceData = pricePoints.map((p) => ({
          time: toTimestamp(p.time),
          value: p.price!,
        }));
        priceSeries.setData(priceData);
      }

      chart.timeScale().fitContent();

      // 响应式
      const resizeObserver = new ResizeObserver((entries) => {
        if (entries[0] && chartRef.current) {
          chartRef.current.applyOptions({
            width: entries[0].contentRect.width,
          });
        }
      });
      resizeObserver.observe(containerRef.current!);

      return () => {
        resizeObserver.disconnect();
      };
    });

    return () => {
      disposed = true;
      if (chartRef.current) {
        chartRef.current.remove();
        chartRef.current = null;
      }
    };
  }, [data, height]);

  // 汇总指标
  const latest = data.length > 0 ? data[data.length - 1] : null;

  return (
    <div className="relative">
      {/* 图例 */}
      <div className="absolute top-2 left-3 z-10 flex items-center gap-4 text-[10px]">
        <span className="flex items-center gap-1">
          <span className="w-3 h-0.5 bg-red-500 inline-block rounded" />
          <span className="text-gray-600">主力 (超大单+大单)</span>
        </span>
        <span className="flex items-center gap-1">
          <span className="w-3 h-0.5 bg-green-500 inline-block rounded" />
          <span className="text-gray-600">散户 (中单+小单)</span>
        </span>
        <span className="flex items-center gap-1">
          <span className="w-3 h-0.5 bg-orange-500 inline-block rounded" />
          <span className="text-gray-600">大单强度</span>
        </span>
        <span className="flex items-center gap-1">
          <span className="w-4 h-[2px] bg-violet-600 inline-block rounded" />
          <span className="text-gray-600">股价</span>
        </span>
        <span className="text-gray-400">| 单位: 万元</span>
      </div>

      {/* 实时数值 */}
      {latest && (
        <div className="absolute top-2 right-3 z-10 flex items-center gap-3 text-[10px]">
          <span className={`font-bold ${latest.main_in >= 0 ? "text-red-600" : "text-green-600"}`}>
            主力 {latest.main_in >= 0 ? "+" : ""}{latest.main_in.toFixed(0)}万
          </span>
          {latest.strength != null && (
            <span className={`font-bold ${latest.strength >= 0.2 ? "text-orange-500" : latest.strength <= -0.2 ? "text-orange-300" : "text-gray-500"}`}>
              强度 {latest.strength >= 0 ? "+" : ""}{latest.strength.toFixed(2)}
            </span>
          )}
          <span className={`font-bold ${latest.retail_in >= 0 ? "text-red-600" : "text-green-600"}`}>
            散户 {latest.retail_in >= 0 ? "+" : ""}{latest.retail_in.toFixed(0)}万
          </span>
        </div>
      )}

      <div ref={containerRef} className="w-full" style={{ height }} />
    </div>
  );
}
