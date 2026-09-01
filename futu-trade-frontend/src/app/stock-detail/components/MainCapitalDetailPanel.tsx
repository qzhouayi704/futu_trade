// 逐笔主力资金分钟明细面板
// 左：主力大单(单笔≥10万)逐分钟 大买/大卖/净额/累计 明细表（最新置顶）
// 右：累计净额(cum)单条曲线
"use client";

import { useState, useCallback, useEffect, useRef } from "react";
import { getMainCapitalDetail } from "@/lib/api/enhanced-heat";
import type { MainCapitalDetailData, MainCapitalDetailRow } from "@/types/enhanced-heat";

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

/** 带符号金额（万元）：正数补 +，负数由 fmtWan 自带 - */
function fmtSigned(v: number | null | undefined): string {
  if (v == null) return "-";
  return `${v > 0 ? "+" : ""}${fmtWan(v)}`;
}

/** 门槛（元）格式化为 万/亿 */
function fmtThr(v: number | null | undefined): string {
  if (v == null) return "-";
  const wan = v / 10000;
  if (wan >= 10000) return `${(wan / 10000).toFixed(1)}亿`;
  return `${wan.toFixed(0)}万`;
}

/** 超大单档突出边框/背景色（红涨绿跌） */
function superBoxColor(v: number): string {
  if (v > 0) return "border-red-300 bg-red-50";
  if (v < 0) return "border-green-300 bg-green-50";
  return "border-border";
}

// ==================== 分档累计净额曲线 ====================

// 四档累计走势的系列定义（颜色避开红/绿，避免与净额正负色混淆）
const TIER_SERIES: { name: string; color: string; width: number; get: (p: MainCapitalDetailRow) => number }[] = [
  { name: "超大单", color: "#2a78d6", width: 2, get: (p) => p.super_cum ?? 0 },
  { name: "大单", color: "#d99000", width: 2, get: (p) => p.large_cum ?? 0 },
  { name: "中单", color: "#7c5cff", width: 2, get: (p) => p.mid_cum ?? 0 },
  { name: "总≥10万", color: "#e5703e", width: 2.5, get: (p) => p.cum },
];

function CumNetChart({ rows, tradeDate, height = 360 }: { rows: MainCapitalDetailRow[]; tradeDate: string; height?: number }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const legendRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<ReturnType<typeof import("lightweight-charts").createChart> | null>(null);

  useEffect(() => {
    if (!containerRef.current || rows.length === 0) return;
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
        layout: { background: { color: "transparent" }, textColor: "#6b7280", fontSize: 11 },
        grid: { vertLines: { color: "#f0f0f0" }, horzLines: { color: "#f0f0f0" } },
        crosshair: { mode: CrosshairMode.Magnet },
        rightPriceScale: { borderColor: "#e5e7eb", scaleMargins: { top: 0.12, bottom: 0.12 } },
        timeScale: { borderColor: "#e5e7eb", timeVisible: true, secondsVisible: false, barSpacing: 8, minBarSpacing: 3 },
      });
      chartRef.current = chart;

      // trade_date(YYYY-MM-DD) + HH:MM -> Unix 时间戳（补偿本地时区，使横轴显示 HK 分钟）
      const [yy, mm, dd] = tradeDate.split("-").map(Number);
      const tzOffsetSec = new Date().getTimezoneOffset() * 60;
      const toTimestamp = (hhmm: string) => {
        const [h, m] = hhmm.split(":").map(Number);
        const d = new Date(yy || 1970, (mm || 1) - 1, dd || 1, h || 0, m || 0);
        return Math.floor(d.getTime() / 1000 - tzOffsetSec) as unknown as import("lightweight-charts").Time;
      };

      // 0 基线（虚线，先加使其位于底层）
      const zeroSeries = chart.addLineSeries({
        color: "#d1d5db",
        lineWidth: 1,
        lineStyle: LineStyle.Dashed,
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: false,
      });
      zeroSeries.setData(rows.map((p) => ({ time: toTimestamp(p.time), value: 0 })));

      // 四档累计线
      const sers = TIER_SERIES.map((s) => {
        const ser = chart.addLineSeries({
          color: s.color,
          lineWidth: s.width as 1 | 2 | 3 | 4,
          priceLineVisible: false,
          lastValueVisible: false,
          crosshairMarkerRadius: 3,
          priceFormat: { type: "volume" },
        });
        ser.setData(rows.map((p) => ({ time: toTimestamp(p.time), value: s.get(p) })));
        return ser;
      });

      // 图例（悬停时显示该时刻各档累计，未悬停显示收盘/最新值）
      const last = rows[rows.length - 1];
      const renderLegend = (vals: number[]) => {
        if (!legendRef.current) return;
        legendRef.current.innerHTML = TIER_SERIES.map((s, i) => {
          const v = vals[i];
          const vc = v > 0 ? "#dc2626" : v < 0 ? "#16a34a" : "#9ca3af";
          return (
            `<span style="display:inline-flex;align-items:center;gap:4px;margin-right:12px;white-space:nowrap">` +
            `<span style="width:14px;height:3px;border-radius:2px;background:${s.color};display:inline-block"></span>` +
            `<span style="color:#6b7280">${s.name}</span>` +
            `<span style="font-weight:600;font-variant-numeric:tabular-nums;color:${vc}">${fmtSigned(v)}</span>` +
            `</span>`
          );
        }).join("");
      };
      renderLegend(TIER_SERIES.map((s) => s.get(last)));

      chart.subscribeCrosshairMove((param: { time?: unknown; seriesData?: Map<unknown, unknown> }) => {
        if (!param || param.time == null || !param.seriesData) {
          renderLegend(TIER_SERIES.map((s) => s.get(last)));
          return;
        }
        const vals = sers.map((ser) => {
          const d = param.seriesData!.get(ser) as { value?: number } | undefined;
          return d && typeof d.value === "number" ? d.value : 0;
        });
        renderLegend(vals);
      });

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
  }, [rows, tradeDate, height]);

  return (
    <div className="relative w-full" style={{ height }}>
      <div ref={containerRef} className="w-full" style={{ height }} />
      <div ref={legendRef} className="absolute top-1 left-2 z-10 flex flex-wrap gap-y-0.5 text-[11px] pointer-events-none" />
    </div>
  );
}

// ==================== 主面板 ====================

export function MainCapitalDetailPanel({ stockCode }: { stockCode: string }) {
  const [data, setData] = useState<MainCapitalDetailData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    if (!stockCode.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const res = await getMainCapitalDetail(stockCode.trim());
      if (res.success) {
        setData(res.data);
        if (!res.data || res.data.rows.length === 0) setError("今日暂无逐笔数据");
      }
    } catch {
      setError("获取主力资金明细失败");
    } finally {
      setLoading(false);
    }
  }, [stockCode]);

  useEffect(() => {
    if (stockCode.trim()) fetchData();
  }, [stockCode, fetchData]);

  // 30 秒自动刷新
  useEffect(() => {
    if (!stockCode.trim()) return;
    const timer = setInterval(fetchData, 30000);
    return () => clearInterval(timer);
  }, [stockCode, fetchData]);

  const rows = data?.rows ?? [];
  const summary = data?.summary ?? null;
  // 表格最新置顶（后端按时间升序，倒序展示便于盯盘）
  const tableRows = [...rows].reverse();
  // 背离：超大单（真机构）与总口径（含中小单）方向相反 —— "大钱 vs 小钱"打架
  const diverge =
    summary?.super_net != null &&
    summary.cum_net != null &&
    summary.super_net !== 0 &&
    Math.sign(summary.super_net) !== Math.sign(summary.cum_net);

  return (
    <div className="bg-card rounded-lg shadow p-6">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-lg font-semibold text-foreground flex items-center gap-2">
          <svg className="w-5 h-5 text-amber-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
          </svg>
          逐笔主力资金明细
          {data && (
            <span className="text-[11px] font-normal text-muted-foreground">
              {data.super_threshold && data.large_threshold
                ? `超大单≥${fmtThr(data.super_threshold)} · 大单${fmtThr(data.large_threshold)}~${fmtThr(data.super_threshold)} · 中单${fmtThr(data.threshold)}~${fmtThr(data.large_threshold)}`
                : `主力大单 ≥ ${(data.threshold / 10000).toFixed(0)}万/笔`}
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
        <div className="mb-4 space-y-2">
          {/* 第一排：总口径（≥10万合计，含中小单） */}
          <div className="flex flex-wrap items-center gap-x-6 gap-y-1 text-sm">
            <span className="text-muted-foreground">
              累计净额{" "}
              <span className={`font-semibold ${pnColor(summary.cum_net)}`}>
                {summary.cum_net >= 0 ? "+" : ""}
                {fmtWan(summary.cum_net)}
              </span>
            </span>
            <span className="text-muted-foreground">
              大买 <span className="font-medium text-red-600">{fmtWan(summary.total_big_buy)}</span>
            </span>
            <span className="text-muted-foreground">
              大卖 <span className="font-medium text-green-600">{fmtWan(summary.total_big_sell)}</span>
            </span>
            {summary.buy_ratio != null && (
              <span className="text-muted-foreground">
                买占比 <span className="font-medium text-foreground">{(summary.buy_ratio * 100).toFixed(1)}%</span>
              </span>
            )}
          </div>

          {/* 第二排：分档净额（超大单突出，一眼看清"大钱还是小钱"） */}
          {summary.super_net != null && (
            <div className="flex flex-wrap items-center gap-2 text-xs">
              <span className="text-muted-foreground mr-1">分档净额</span>
              <span className={`inline-flex items-center gap-1 rounded-md border-2 px-2 py-0.5 font-semibold ${superBoxColor(summary.super_net)}`}>
                <span className="text-foreground">超大单</span>
                <span className={pnColor(summary.super_net)}>{fmtSigned(summary.super_net)}</span>
              </span>
              <span className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-0.5">
                <span className="text-muted-foreground">大单</span>
                <span className={pnColor(summary.large_net ?? 0)}>{fmtSigned(summary.large_net)}</span>
              </span>
              <span className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-0.5">
                <span className="text-muted-foreground">中单</span>
                <span className={pnColor(summary.mid_net ?? 0)}>{fmtSigned(summary.mid_net)}</span>
              </span>
            </div>
          )}

          {/* 背离横幅：超大单（真机构）与总口径方向相反 */}
          {diverge && summary.super_net != null && (
            <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
              ⚠{" "}
              {summary.super_net < 0
                ? `大钱在出货、小钱在接盘：超大单净卖 ${fmtWan(Math.abs(summary.super_net))}，但 ≥10万口径净买 ${fmtWan(Math.abs(summary.cum_net))}`
                : `大钱在进场、小钱在派发：超大单净买 ${fmtWan(Math.abs(summary.super_net))}，但 ≥10万口径净卖 ${fmtWan(Math.abs(summary.cum_net))}`}
            </div>
          )}
        </div>
      )}

      {error && rows.length === 0 && <p className="text-sm text-muted-foreground py-8 text-center">{error}</p>}

      {rows.length > 0 && data && (
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-5 items-start">
          {/* 左：主力明细表 */}
          <div className="max-h-[420px] overflow-y-auto">
            <table className="w-full text-right text-xs">
              <thead className="sticky top-0 bg-card">
                <tr className="border-b border-border text-muted-foreground">
                  <th className="py-1.5 px-2 text-left font-medium">时刻</th>
                  <th className="py-1.5 px-2 font-medium">价格</th>
                  <th className="py-1.5 px-2 font-medium">涨幅</th>
                  <th className="py-1.5 px-2 font-medium">大买(万)</th>
                  <th className="py-1.5 px-2 font-medium">大卖(万)</th>
                  <th className="py-1.5 px-2 font-medium">超大单净(万)</th>
                  <th className="py-1.5 px-2 font-medium">净额(万)</th>
                  <th className="py-1.5 px-2 font-medium">累计(万)</th>
                </tr>
              </thead>
              <tbody className="font-mono">
                {tableRows.map((r) => (
                  <tr key={r.time} className="border-b border-border/50 hover:bg-muted/50">
                    <td className="py-1 px-2 text-left text-foreground">{r.time}</td>
                    <td className="py-1 px-2 text-foreground">{r.price != null ? r.price.toFixed(2) : "-"}</td>
                    <td className={`py-1 px-2 ${pnColor(r.change_pct)}`}>
                      {r.change_pct != null ? `${r.change_pct > 0 ? "+" : ""}${r.change_pct.toFixed(1)}%` : "-"}
                    </td>
                    <td className="py-1 px-2 text-red-600">{r.big_buy ? r.big_buy.toFixed(0) : "0"}</td>
                    <td className="py-1 px-2 text-green-600">{r.big_sell ? r.big_sell.toFixed(0) : "0"}</td>
                    <td className={`py-1 px-2 font-medium ${pnColor(r.super_net)}`}>
                      {r.super_net != null && r.super_net !== 0
                        ? `${r.super_net > 0 ? "+" : ""}${r.super_net.toFixed(0)}`
                        : "0"}
                    </td>
                    <td className={`py-1 px-2 font-medium ${pnColor(r.net)}`}>
                      {r.net > 0 ? "+" : ""}
                      {r.net.toFixed(0)}
                    </td>
                    <td className={`py-1 px-2 font-medium ${pnColor(r.cum)}`}>
                      {r.cum > 0 ? "+" : ""}
                      {r.cum.toFixed(0)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* 右：累计净额曲线 */}
          <div>
            <div className="flex items-center justify-between mb-1 px-1">
              <span className="text-xs font-medium text-foreground">分档累计净额走势</span>
              <span className="text-[10px] text-muted-foreground">超大单/大单/中单/总 · 万元 · 30秒刷新</span>
            </div>
            <CumNetChart rows={rows} tradeDate={data.trade_date} />
          </div>
        </div>
      )}
    </div>
  );
}
