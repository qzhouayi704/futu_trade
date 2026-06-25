// 近几日主力资金流向面板（可切换口径）
// · 逐笔大单：ticker_data 大单≥10万按日聚合，与盘中逐笔面板同源（近几个有效交易日）
// · 富途聚合：capital_flow_daily 富途主力净流入，历史更长但口径不同，可能与逐笔不同向
// 左：每日 主力净额(逐笔下含大买/大卖) 明细表（最新置顶）；右：每日主力净额柱状走势
"use client";

import { useState, useCallback, useEffect, useRef } from "react";
import { getMainCapitalDaily, getCapitalFlowHistory } from "@/lib/api/enhanced-heat";

type Mode = "tick" | "futu30" | "futu90";

/** 统一后的单日结构（万元）；大买/大卖仅逐笔口径有 */
interface UDay {
  date: string;
  net: number;
  big_buy?: number;
  big_sell?: number;
}

const MODES: { key: Mode; label: string }[] = [
  { key: "tick", label: "逐笔大单" },
  { key: "futu30", label: "富途30天" },
  { key: "futu90", label: "富途90天" },
];

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

function toDateStr(d: Date): string {
  return d.toISOString().slice(0, 10);
}

// ==================== 每日主力净额柱状走势 ====================

function DailyNetChart({ days, height = 300 }: { days: UDay[]; height?: number }) {
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

      // 柱数多时收窄间距
      const barSpacing = days.length > 40 ? 6 : days.length > 15 ? 12 : 36;

      const chart = createChart(containerRef.current, {
        width: containerRef.current.clientWidth,
        height,
        layout: { background: { color: "transparent" }, textColor: "#6b7280", fontSize: 11 },
        grid: { vertLines: { color: "#f0f0f0" }, horzLines: { color: "#f0f0f0" } },
        crosshair: { mode: CrosshairMode.Magnet },
        rightPriceScale: { borderColor: "#e5e7eb", scaleMargins: { top: 0.15, bottom: 0.15 } },
        timeScale: { borderColor: "#e5e7eb", timeVisible: false, barSpacing, minBarSpacing: 4 },
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
  const [mode, setMode] = useState<Mode>("tick");
  const [days, setDays] = useState<UDay[]>([]);
  const [threshold, setThreshold] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isFutu = mode !== "tick";

  const fetchData = useCallback(async (m: Mode) => {
    if (!stockCode.trim()) return;
    setLoading(true);
    setError(null);
    try {
      if (m === "tick") {
        const res = await getMainCapitalDaily(stockCode.trim());
        if (res.success) {
          const d = res.data;
          setThreshold(d?.threshold ?? null);
          setDays((d?.days ?? []).map((x) => ({ date: x.date, net: x.net, big_buy: x.big_buy, big_sell: x.big_sell })));
          if (!d || d.days.length === 0) setError("暂无逐笔历史数据");
        }
      } else {
        const span = m === "futu30" ? 30 : 90;
        const end = new Date();
        const start = new Date();
        start.setDate(end.getDate() - span);
        const res = await getCapitalFlowHistory(stockCode.trim(), toDateStr(start), toDateStr(end));
        if (res.success) {
          // 富途 date 可能带 " 00:00:00"，统一裁成 YYYY-MM-DD（图表业务日 + 表格标签都需要）
          const hist = (res.data?.history ?? []).map((x) => ({ date: x.date.slice(0, 10), net: x.net_inflow / 10000 }));
          const sorted = hist.sort((a, b) => a.date.localeCompare(b.date));
          setThreshold(null);
          setDays(sorted);
          if (sorted.length === 0) setError("暂无历史资金流向数据");
        }
      }
    } catch {
      setError("获取主力资金历史失败");
    } finally {
      setLoading(false);
    }
  }, [stockCode]);

  // stockCode / mode 变化时加载
  useEffect(() => {
    if (stockCode.trim()) fetchData(mode);
  }, [stockCode, mode, fetchData]);

  // 仅逐笔口径 60 秒刷新（当日那根会变）；富途日线静态不刷
  useEffect(() => {
    if (!stockCode.trim() || mode !== "tick") return;
    const timer = setInterval(() => fetchData("tick"), 60000);
    return () => clearInterval(timer);
  }, [stockCode, mode, fetchData]);

  // 汇总
  const cumNet = days.reduce((s, d) => s + d.net, 0);
  const posDays = days.filter((d) => d.net > 0).length;
  const tableDays = [...days].reverse(); // 最新置顶

  const subtitle = isFutu
    ? `富途聚合口径 · ${mode === "futu30" ? 30 : 90}天`
    : threshold != null
    ? `逐笔大单 ≥ ${(threshold / 10000).toFixed(0)}万/笔 · 近 ${days.length} 日`
    : `逐笔大单 · 近 ${days.length} 日`;

  return (
    <div className="bg-card rounded-lg shadow p-6">
      <div className="flex items-center justify-between mb-4 gap-3 flex-wrap">
        <h3 className="text-lg font-semibold text-foreground flex items-center gap-2">
          <svg className="w-5 h-5 text-indigo-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
          </svg>
          近几日主力资金流向
          <span className="text-[11px] font-normal text-muted-foreground">{subtitle}</span>
        </h3>
        <div className="flex items-center gap-2">
          {/* 口径切换 */}
          <div className="flex items-center gap-1 bg-muted/40 p-0.5 rounded-lg">
            {MODES.map((m) => (
              <button
                key={m.key}
                onClick={() => setMode(m.key)}
                disabled={loading}
                className={`px-2.5 py-1 text-xs rounded-md transition-colors disabled:opacity-50 ${
                  mode === m.key ? "bg-card text-foreground shadow-sm font-medium" : "text-muted-foreground hover:text-foreground"
                }`}
              >
                {m.label}
              </button>
            ))}
          </div>
          <button
            onClick={() => fetchData(mode)}
            disabled={loading}
            className="text-xs text-muted-foreground hover:text-foreground disabled:opacity-50"
          >
            {loading ? "刷新中..." : "刷新"}
          </button>
        </div>
      </div>

      {/* 富途口径提示 */}
      {isFutu && days.length > 0 && (
        <p className="text-[11px] text-amber-600 dark:text-amber-500 mb-3">
          ⚠ 富途聚合口径，与上方逐笔大单口径不同，可能出现方向相反，仅供历史趋势参考。
        </p>
      )}

      {/* 汇总条 */}
      {days.length > 0 && (
        <div className="flex flex-wrap items-center gap-x-6 gap-y-1 mb-4 text-sm">
          <span className="text-muted-foreground">
            区间累计{" "}
            <span className={`font-semibold ${pnColor(cumNet)}`}>
              {cumNet >= 0 ? "+" : ""}
              {fmtWan(cumNet)}
            </span>
          </span>
          <span className="text-muted-foreground">
            净流入天数 <span className="font-medium text-foreground">{posDays}/{days.length}</span>
          </span>
        </div>
      )}

      {error && days.length === 0 && <p className="text-sm text-muted-foreground py-8 text-center">{error}</p>}

      {days.length > 0 && (
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-5 items-start">
          {/* 左：每日明细表 */}
          <div className="max-h-[360px] overflow-y-auto">
            <table className="w-full text-right text-xs">
              <thead className="sticky top-0 bg-card">
                <tr className="border-b border-border text-muted-foreground">
                  <th className="py-1.5 px-2 text-left font-medium">日期</th>
                  {!isFutu && <th className="py-1.5 px-2 font-medium">大买(万)</th>}
                  {!isFutu && <th className="py-1.5 px-2 font-medium">大卖(万)</th>}
                  <th className="py-1.5 px-2 font-medium">主力净额(万)</th>
                </tr>
              </thead>
              <tbody className="font-mono">
                {tableDays.map((d) => (
                  <tr key={d.date} className="border-b border-border/50 hover:bg-muted/50">
                    <td className="py-1.5 px-2 text-left text-foreground">{d.date.slice(5)}</td>
                    {!isFutu && <td className="py-1.5 px-2 text-red-600">{(d.big_buy ?? 0).toFixed(0)}</td>}
                    {!isFutu && <td className="py-1.5 px-2 text-green-600">{(d.big_sell ?? 0).toFixed(0)}</td>}
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
