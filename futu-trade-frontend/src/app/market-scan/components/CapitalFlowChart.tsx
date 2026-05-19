// 逐笔买卖力量走势图
// 股价折线（右轴） + 分钟净主动买入柱状图（左轴）

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

    import("lightweight-charts").then(({ createChart, CrosshairMode }) => {
      if (disposed || !containerRef.current) return;

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
        crosshair: { mode: CrosshairMode.Magnet },
        rightPriceScale: { borderColor: "#e5e7eb" },
        timeScale: {
          borderColor: "#e5e7eb",
          timeVisible: true,
          secondsVisible: false,
        },
      });

      chartRef.current = chart;

      // HH:MM -> Unix timestamp (补偿时区)
      const today = new Date();
      const tzOffsetSec = today.getTimezoneOffset() * 60;
      const toTimestamp = (hhmm: string) => {
        const [h, m] = hhmm.split(':').map(Number);
        const d = new Date(today.getFullYear(), today.getMonth(), today.getDate(), h || 0, m || 0);
        return Math.floor(d.getTime() / 1000 - tzOffsetSec) as unknown as import("lightweight-charts").Time;
      };

      // === 1. 净主动买入柱状图（左轴）===
      const netBuySeries = chart.addHistogramSeries({
        priceScaleId: "left",
        title: "净买入",
        priceFormat: { type: "volume" },
        lastValueVisible: true,
      });

      const netBuyData = data.map((p) => {
        const val = (p as any).net_buy as number ?? (p as any).main_in ?? 0;
        return {
          time: toTimestamp(p.time),
          value: val,
          color: val >= 0 ? "rgba(239, 68, 68, 0.7)" : "rgba(34, 197, 94, 0.7)",
        };
      });
      netBuySeries.setData(netBuyData);

      // === 2. 累计净主动买入线（左轴，更淡）===
      const cumPoints = data.filter(p => (p as any).cum_net != null);
      if (cumPoints.length > 3) {
        const cumSeries = chart.addAreaSeries({
          topColor: "rgba(99, 102, 241, 0.15)",
          bottomColor: "rgba(99, 102, 241, 0.02)",
          lineColor: "#6366f1",
          lineWidth: 1,
          title: "累计净买",
          priceScaleId: "left",
          lastValueVisible: true,
        });

        // 零轴虚线
        const zeroSeries = chart.addLineSeries({
          color: "#9ca3af",
          lineWidth: 1,
          lineStyle: 2,
          title: "",
          priceLineVisible: false,
          lastValueVisible: false,
          crosshairMarkerVisible: false,
          priceScaleId: "left",
        });

        cumSeries.setData(cumPoints.map(p => ({
          time: toTimestamp(p.time),
          value: (p as any).cum_net as number ?? 0,
        })));
        zeroSeries.setData(cumPoints.map(p => ({
          time: toTimestamp(p.time),
          value: 0,
        })));
      }

      // === 3. 股价走势线（右轴）===
      const pricePoints = data.filter(p => p.price != null && p.price > 0);
      if (pricePoints.length > 5) {
        const priceSeries = chart.addLineSeries({
          color: "#7c3aed",
          lineWidth: 2,
          title: "股价",
          priceScaleId: "right",
          lastValueVisible: true,
          priceLineVisible: true,
          priceLineColor: "#7c3aed",
          priceLineStyle: 2,
        });

        priceSeries.setData(pricePoints.map(p => ({
          time: toTimestamp(p.time),
          value: p.price!,
        })));

        chart.priceScale("right").applyOptions({
          scaleMargins: { top: 0.08, bottom: 0.08 },
          visible: true,
          borderColor: "#7c3aed",
        });
      }

      // 左轴配置
      chart.priceScale("left").applyOptions({
        scaleMargins: { top: 0.08, bottom: 0.08 },
        visible: true,
        borderColor: "#d1d5db",
      });

      chart.timeScale().fitContent();

      // 响应式
      const resizeObserver = new ResizeObserver((entries) => {
        if (entries[0] && chartRef.current) {
          chartRef.current.applyOptions({ width: entries[0].contentRect.width });
        }
      });
      resizeObserver.observe(containerRef.current!);

      return () => { resizeObserver.disconnect(); };
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
  const latestAny = latest as any;
  const cumNet = latestAny?.cum_net as number | undefined;
  const netBuy = latestAny?.net_buy as number | undefined;

  return (
    <div className="relative">
      {/* 图例 */}
      <div className="absolute top-2 left-3 z-10 flex items-center gap-4 text-[10px]">
        <span className="flex items-center gap-1">
          <span className="w-3 h-3 bg-red-400/70 inline-block rounded-sm" />
          <span className="text-gray-600">主动买入</span>
        </span>
        <span className="flex items-center gap-1">
          <span className="w-3 h-3 bg-green-400/70 inline-block rounded-sm" />
          <span className="text-gray-600">主动卖出</span>
        </span>
        <span className="flex items-center gap-1">
          <span className="w-3 h-0.5 bg-indigo-500 inline-block rounded" />
          <span className="text-gray-600">累计净买</span>
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
          {netBuy != null && (
            <span className={`font-bold ${netBuy >= 0 ? "text-red-600" : "text-green-600"}`}>
              本分钟 {netBuy >= 0 ? "+" : ""}{netBuy.toFixed(0)}万
            </span>
          )}
          {cumNet != null && (
            <span className={`font-bold ${cumNet >= 0 ? "text-red-600" : "text-green-600"}`}>
              累计 {cumNet >= 0 ? "+" : ""}{cumNet.toFixed(0)}万
            </span>
          )}
          {latest.price != null && latest.price > 0 && (
            <span className="font-bold text-violet-600">
              ${latest.price.toFixed(3)}
            </span>
          )}
        </div>
      )}

      <div ref={containerRef} className="w-full" style={{ height }} />
    </div>
  );
}
