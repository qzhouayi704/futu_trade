// 近几日主力资金流向面板（逐笔大单≥10万口径，与盘中逐笔面板同源）
// 左：每个交易日 大买/大卖/主力净额 明细表（最新置顶）
// 右：每日主力净额 柱状走势（红流入/绿流出）
"use client";

import { useState, useCallback, useEffect, useRef } from "react";
import { getMainCapitalDaily } from "@/lib/api/enhanced-heat";
import type { MainCapitalDailyData, MainCapitalDailyDay } from "@/types/enhanced-heat";

/** 金额格式化：入参单位为「万元」 */
function fmtWan(v: number | null | undefined): string {
  if (v == null) return "-";
  const abs = Math.abs(v);
  if (abs >= 10000) return `${(v / 10000).toFixed(2)}亿`;
  return `${v.toFixed(0)}万`;
}

/** 涨跌色：>0 红，<0 绿 */
function pnColor(v: number | null | undefined): string {
  if (v == null || v === 0) return "text-muted-foreground";
  return v > 0 ? "text-red-600" : "text-green-600";
}

// ==================== 每日主力净额柱状走势 ====================

function DailyNetChart({ days, height = 300 }: { days: MainCapitalDailyDay[]; height?: number }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<ReturnType<typeof import("lightweight-charts").createChart> | null>(null);

  useEffect(() => {
    if (!containerRef.current || days.length === 0) return;
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
        layout: { background: { color: "transparent" }, textColor: "#6b7280", fontSize: 11 },
        grid: { vertLines: { color: "#f0f0f0" }, horzLines: { color: "#f0f0f0" } },
        crosshair: { mode: CrosshairMode.Magnet },
        rightPriceScale: { borderColor: "#e5e7eb", scaleMargins: { top: 0.15, bottom: 0.15 } },
        timeScale: { borderColor: "#e5e7eb", timeVisible: false, barSpacing: 36, minBarSpacing: 16 },
      });
      chartRef.current = chart;

      const netSeries = chart.addHistogramSeries({
        priceFormat: { type: "volume" },
        title: "主力净额",
        lastValueVisible: true,
      });
      // 每日时间用业务日字符串（lightweight-charts 原生支持）
      netSeries.setData(
        days.map((d) => ({
          time: d.date as unknown as import("lightweight-charts").Time,
          value: d.net,
          color: d.net >= 0 ? "rgba(239, 68, 68, 0.7)" : "rgba(34, 197, 94, 0.7)",
        }))
      );

      chart.timeScale().fitContent();

      const ro = new ResizeObserver((entries) => {
        if (entries[0] && chartRef.current) chartRef.current.applyOptions({ width: entries[0].contentRect.width });
      });
      ro.observe(containerRef.current);
      return () => ro.disconnect();
    });

    return () => {
      disposed = true;
      if (chartRef.current) {
        chartRef.current.remove();
        chartRef.current = null;
      }
    };
  }, [days, height]);

  return <div ref={containerRef} className="w-full" style={{ height }} />;
}

// ==================== 主面板 ====================

export function MainCapitalDailyPanel({ stockCode }: { stockCode: string }) {
  const [data, setData] = useState<MainCapitalDailyData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    if (!stockCode.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const res = await getMainCapitalDaily(stockCode.trim());
      if (res.success) {
        setData(res.data);
        if (!res.data || res.data.days.length === 0) setError("暂无逐笔历史数据");
      }
    } catch {
      setError("获取近几日主力资金失败");
    } finally {
      setLoading(false);
    }
  }, [stockCode]);

  useEffect(() => {
    if (stockCode.trim()) fetchData();
  }, [stockCode, fetchData]);

  // 60 秒刷新（仅当日那根柱会变）
  useEffect(() => {
    if (!stockCode.trim()) return;
    const timer = setInterval(fetchData, 60000);
    return () => clearInterval(timer);
  }, [stockCode, fetchData]);

  const days = data?.days ?? [];
  const summary = data?.summary ?? null;
  // 表格最新置顶
  const tableDays = [...days].reverse();

  return (
    <div className="bg-card rounded-lg shadow p-6">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-lg font-semibold text-foreground flex items-center gap-2">
          <svg className="w-5 h-5 text-indigo-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
          </svg>
          近几日主力资金流向
          {data && (
            <span className="text-[11px] font-normal text-muted-foreground">
              逐笔大单 ≥ {(data.threshold / 10000).toFixed(0)}万/笔 · 近 {days.length} 日
            </span>
          )}
        </h3>
        <button
          onClick={fetchData}
          disabled={loading}
          className="text-xs text-muted-foreground hover:text-foreground disabled:opacity-50"
        >
          {loading ? "刷新中..." : "刷新"}
        </button>
      </div>

      {/* 汇总条 */}
      {summary && (
        <div className="flex flex-wrap items-center gap-x-6 gap-y-1 mb-4 text-sm">
          <span className="text-muted-foreground">
            区间累计{" "}
            <span className={`font-semibold ${pnColor(summary.cum_net)}`}>
              {summary.cum_net >= 0 ? "+" : ""}
              {fmtWan(summary.cum_net)}
            </span>
          </span>
          <span className="text-muted-foreground">
            净流入天数 <span className="font-medium text-foreground">{summary.positive_days}/{summary.total_days}</span>
          </span>
        </div>
      )}

      {error && days.length === 0 && <p className="text-sm text-muted-foreground py-8 text-center">{error}</p>}

      {days.length > 0 && data && (
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-5 items-start">
          {/* 左：每日明细表 */}
          <div className="max-h-[360px] overflow-y-auto">
            <table className="w-full text-right text-xs">
              <thead className="sticky top-0 bg-card">
                <tr className="border-b border-border text-muted-foreground">
                  <th className="py-1.5 px-2 text-left font-medium">日期</th>
                  <th className="py-1.5 px-2 font-medium">大买(万)</th>
                  <th className="py-1.5 px-2 font-medium">大卖(万)</th>
                  <th className="py-1.5 px-2 font-medium">主力净额(万)</th>
                </tr>
              </thead>
              <tbody className="font-mono">
                {tableDays.map((d) => (
                  <tr key={d.date} className="border-b border-border/50 hover:bg-muted/50">
                    <td className="py-1.5 px-2 text-left text-foreground">{d.date.slice(5)}</td>
                    <td className="py-1.5 px-2 text-red-600">{d.big_buy.toFixed(0)}</td>
                    <td className="py-1.5 px-2 text-green-600">{d.big_sell.toFixed(0)}</td>
                    <td className={`py-1.5 px-2 font-semibold ${pnColor(d.net)}`}>
                      {d.net > 0 ? "+" : ""}
                      {d.net.toFixed(0)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* 右：每日主力净额柱状走势 */}
          <div>
            <div className="flex items-center justify-between mb-1 px-1">
              <span className="text-xs font-medium text-foreground">每日主力净额走势</span>
              <span className="text-[10px] text-muted-foreground">红=净流入 · 绿=净流出 · 万元</span>
            </div>
            <DailyNetChart days={days} />
          </div>
        </div>
      )}
    </div>
  );
}
