// 逐笔买卖力量走势图（重构版）
// 布局：股价折线（右轴，主区域） + 累计净买线（左轴） + 分钟净买柱状图（底部20%叠加层）

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

    import("lightweight-charts").then(({ createChart, CrosshairMode, LineStyle }) => {
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
          vertLines: { color: "#f0f0f0" },
          horzLines: { color: "#f0f0f0" },
        },
        crosshair: { mode: CrosshairMode.Magnet },
        rightPriceScale: {
          borderColor: "#e5e7eb",
          scaleMargins: { top: 0.05, bottom: 0.4 },  // 底部留40%给柱状图
        },
        leftPriceScale: {
          borderColor: "#d1d5db",
          visible: true,
          scaleMargins: { top: 0.05, bottom: 0.4 },  // 与右轴对齐
        },
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

      // === 1. 股价走势线（右轴，视觉主体）===
      const pricePoints = data.filter(p => p.price != null && p.price > 0);
      if (pricePoints.length > 3) {
        const priceSeries = chart.addLineSeries({
          color: "#7c3aed",
          lineWidth: 2,
          title: "股价",
          priceScaleId: "right",
          lastValueVisible: true,
          priceLineVisible: true,
          priceLineColor: "#7c3aed",
          priceLineStyle: 2,
          crosshairMarkerRadius: 4,
          priceFormat: {
            type: "price",
            precision: pricePoints[0].price! >= 100 ? 2 : 3,
            minMove: pricePoints[0].price! >= 100 ? 0.01 : 0.001,
          },
        });

        priceSeries.setData(pricePoints.map(p => ({
          time: toTimestamp(p.time),
          value: p.price!,
        })));
      }

      // === 2. 累计净买线（左轴，趋势参考）===
      const cumPoints = data.filter(p => (p as any).cum_net != null);
      if (cumPoints.length > 3) {
        const cumSeries = chart.addLineSeries({
          color: "#3b82f6",
          lineWidth: 2,
          title: "累计净买",
          priceScaleId: "left",
          lastValueVisible: true,
          crosshairMarkerRadius: 3,
          priceFormat: { type: "volume" },
        });

        cumSeries.setData(cumPoints.map(p => ({
          time: toTimestamp(p.time),
          value: (p as any).cum_net as number ?? 0,
        })));

        // 零轴虚线（左轴）
        const zeroSeries = chart.addLineSeries({
          color: "#d1d5db",
          lineWidth: 1,
          lineStyle: LineStyle.Dashed,
          title: "",
          priceLineVisible: false,
          lastValueVisible: false,
          crosshairMarkerVisible: false,
          priceScaleId: "left",
        });
        zeroSeries.setData(cumPoints.map(p => ({
          time: toTimestamp(p.time),
          value: 0,
        })));
      }

      // === 3. 分钟净买柱状图（底部叠加层）===
      // 正值=主动买入超过卖出（红色朝上），负值=主动卖出超过买入（绿色朝下）
      const netBuySeries = chart.addHistogramSeries({
        priceScaleId: "volume_scale",
        title: "",
        priceFormat: { type: "volume" },
        lastValueVisible: false,
      });

      // 底部45%空间
      chart.priceScale("volume_scale").applyOptions({
        scaleMargins: { top: 0.55, bottom: 0 },
        visible: false,
      });

      netBuySeries.setData(data.map((p) => {
        const val = (p as any).net_buy as number ?? (p as any).main_in ?? 0;
        return {
          time: toTimestamp(p.time),
          value: val,  // 保留正负值，正=净买入朝上，负=净卖出朝下
          color: val >= 0 ? "rgba(239, 68, 68, 0.55)" : "rgba(34, 197, 94, 0.55)",
        };
      }));

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

  const fmtAmt = (v: number) => {
    const abs = Math.abs(v);
    if (abs >= 1e4) return `${(v / 1e4).toFixed(0)}万`;
    return v.toFixed(0);
  };

  return (
    <div className="relative">
      {/* 图例 */}
      <div className="absolute top-2 left-3 z-10 flex items-center gap-4 text-[10px]">
        <span className="flex items-center gap-1">
          <span className="w-3 h-3 bg-red-400/60 inline-block rounded-sm" />
          <span className="text-gray-600">净买入</span>
        </span>
        <span className="flex items-center gap-1">
          <span className="w-3 h-3 bg-green-400/60 inline-block rounded-sm" />
          <span className="text-gray-600">净卖出</span>
        </span>
        <span className="flex items-center gap-1">
          <span className="w-4 h-[2px] bg-blue-500 inline-block rounded" />
          <span className="text-gray-600">累计净买</span>
        </span>
        <span className="flex items-center gap-1">
          <span className="w-4 h-[2px] bg-violet-600 inline-block rounded" />
          <span className="text-gray-600">股价</span>
        </span>
        <span className="text-gray-400">| 万元</span>
      </div>

      {/* 实时数值 */}
      {latest && (
        <div className="absolute top-2 right-3 z-10 flex items-center gap-3 text-[10px]">
          {netBuy != null && (
            <span className={`font-bold ${netBuy >= 0 ? "text-red-600" : "text-green-600"}`}>
              本分钟 {netBuy >= 0 ? "+" : ""}{fmtAmt(netBuy)}
            </span>
          )}
          {cumNet != null && (
            <span className={`font-bold ${cumNet >= 0 ? "text-red-600" : "text-green-600"}`}>
              累计 {cumNet >= 0 ? "+" : ""}{fmtAmt(cumNet)}
            </span>
          )}
          {latest.price != null && latest.price > 0 && (
            <span className="font-bold text-violet-600">
              {latest.price.toFixed(latest.price >= 100 ? 2 : 3)}
            </span>
          )}
        </div>
      )}

      <div ref={containerRef} className="w-full" style={{ height }} />
    </div>
  );
}
