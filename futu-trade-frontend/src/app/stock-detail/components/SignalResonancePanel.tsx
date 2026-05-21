/**
 * 多维信号共振仪表盘
 *
 * 一眼看清所有维度的多空方向是否一致：
 * - 趋势评分 / 成交力量 / 资金流向 / 盘口挂单 / 量能可信
 * - 综合判定 + 信号矛盾提示
 */
"use client";

import { useState, useEffect, useCallback } from "react";
import {
  getSignalResonance,
  type SignalResonanceData,
  type SignalDimension,
} from "@/lib/api/stock-detail-composite";

interface Props {
  stockCode: string;
}

export function SignalResonancePanel({ stockCode }: Props) {
  const [data, setData] = useState<SignalResonanceData | null>(null);
  const [loading, setLoading] = useState(false);

  const fetchData = useCallback(async () => {
    if (!stockCode) return;
    setLoading(true);
    try {
      const res = await getSignalResonance(stockCode);
      if (res.success && res.data) setData(res.data);
    } catch { /* ignore */ }
    setLoading(false);
  }, [stockCode]);

  useEffect(() => {
    fetchData();
    const t = setInterval(fetchData, 15_000);
    return () => clearInterval(t);
  }, [fetchData]);

  if (loading && !data) {
    return (
      <div className="bg-card rounded-xl border border-border p-5 animate-pulse">
        <div className="h-4 w-40 bg-muted rounded mb-4" />
        <div className="space-y-3">
          {[1, 2, 3, 4, 5].map((i) => (
            <div key={i} className="h-6 bg-muted/50 rounded" />
          ))}
        </div>
      </div>
    );
  }

  if (!data) return null;

  const { dimensions, summary } = data;
  const validDims = dimensions.filter((d) => d.score !== null);

  // Verdict styling
  const verdictConfig: Record<string, { color: string; bg: string; border: string }> = {
    "看多": { color: "text-red-500", bg: "bg-red-500/10", border: "border-red-500/30" },
    "看空": { color: "text-green-500", bg: "bg-green-500/10", border: "border-green-500/30" },
    "中性": { color: "text-amber-500", bg: "bg-amber-500/10", border: "border-amber-500/30" },
  };
  const vc = verdictConfig[summary.verdict] || verdictConfig["中性"];

  return (
    <div className="bg-card rounded-xl border border-border overflow-hidden">
      {/* Header */}
      <div className="px-4 py-2.5 bg-gradient-to-r from-purple-500/8 to-pink-500/8 border-b border-border flex items-center justify-between">
        <span className="text-sm font-semibold text-foreground">📡 信号共振面板</span>
        <span className="text-[10px] text-muted-foreground">15s刷新</span>
      </div>

      <div className="p-4">
        {/* Summary row */}
        <div className="flex items-center gap-4 mb-4">
          {/* Score circle */}
          <div className={`relative w-16 h-16 rounded-full ${vc.bg} border-2 ${vc.border} flex items-center justify-center flex-shrink-0`}>
            <div className="text-center">
              <div className={`text-xl font-bold tabular-nums ${vc.color}`}>
                {summary.avg_score.toFixed(0)}
              </div>
              <div className={`text-[9px] font-medium ${vc.color}`}>
                {summary.verdict}
              </div>
            </div>
            {/* Ring indicator */}
            <svg className="absolute inset-0 w-full h-full -rotate-90" viewBox="0 0 64 64">
              <circle
                cx="32" cy="32" r="28"
                fill="none"
                stroke="var(--border)"
                strokeWidth="3"
              />
              <circle
                cx="32" cy="32" r="28"
                fill="none"
                stroke={summary.avg_score >= 60 ? "rgb(239,68,68)" : summary.avg_score >= 40 ? "rgb(245,158,11)" : "rgb(34,197,94)"}
                strokeWidth="3"
                strokeDasharray={`${(summary.avg_score / 100) * 175.9} 175.9`}
                strokeLinecap="round"
              />
            </svg>
          </div>

          {/* Verdict badges */}
          <div className="flex-1 space-y-1.5">
            <div className="flex items-center gap-2 text-xs">
              <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-red-500/10 text-red-500 border border-red-500/20">
                ▲ {summary.bullish_count}多
              </span>
              <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-green-500/10 text-green-500 border border-green-500/20">
                ▼ {summary.bearish_count}空
              </span>
              <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-amber-500/10 text-amber-500 border border-amber-500/20">
                ● {summary.neutral_count}中
              </span>
            </div>
            <div className="text-[11px] text-muted-foreground">
              共振判定：{summary.bullish_count}多 {summary.bearish_count}空 — {summary.verdict}
              {validDims.length < 5 && ` (${validDims.length}/5维度可用)`}
            </div>
          </div>
        </div>

        {/* Dimension bars */}
        <div className="space-y-2">
          {dimensions.map((dim, i) => (
            <DimensionBar key={i} dim={dim} />
          ))}
        </div>

        {/* Conflicts */}
        {summary.conflicts.length > 0 && (
          <div className="mt-3 space-y-1.5">
            {summary.conflicts.map((c, i) => (
              <div
                key={i}
                className="flex items-start gap-2 px-3 py-2 rounded-lg bg-amber-500/8 border border-amber-500/15 text-xs text-amber-600"
              >
                <span className="mt-0.5">⚠</span>
                <span>{c}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ==================== Dimension Bar ====================

function DimensionBar({ dim }: { dim: SignalDimension }) {
  const score = dim.score;
  const hasData = score !== null;
  const s = score ?? 50;

  // Color based on score
  const barColor =
    s >= 60 ? "bg-red-500" : s >= 40 ? "bg-amber-500" : "bg-green-500";
  const labelColor =
    s >= 60 ? "text-red-500" : s >= 40 ? "text-amber-500" : "text-green-500";
  const labelBg =
    s >= 60 ? "bg-red-500/10" : s >= 40 ? "bg-amber-500/10" : "bg-green-500/10";

  return (
    <div className="flex items-center gap-3 group">
      {/* Icon + Name */}
      <div className="flex items-center gap-1.5 w-20 flex-shrink-0">
        <span className="text-sm">{dim.icon}</span>
        <span className="text-xs text-muted-foreground truncate">{dim.name}</span>
      </div>

      {/* Progress bar */}
      <div className="flex-1 h-5 rounded-full bg-muted/50 overflow-hidden relative">
        {hasData ? (
          <>
            <div
              className={`h-full rounded-full ${barColor} transition-all duration-700 ease-out`}
              style={{ width: `${s}%` }}
            />
            {/* Score indicator dot */}
            <div
              className="absolute top-1/2 -translate-y-1/2 w-2.5 h-2.5 rounded-full bg-white border-2 border-current shadow-sm transition-all duration-700"
              style={{
                left: `calc(${s}% - 5px)`,
                borderColor: s >= 60 ? "rgb(239,68,68)" : s >= 40 ? "rgb(245,158,11)" : "rgb(34,197,94)",
              }}
            />
          </>
        ) : (
          <div className="h-full flex items-center justify-center text-[10px] text-muted-foreground">
            数据不可用
          </div>
        )}
      </div>

      {/* Score + Label */}
      <div className="flex items-center gap-1.5 w-24 flex-shrink-0 justify-end">
        {hasData ? (
          <>
            <span className={`text-sm font-bold tabular-nums ${labelColor}`}>{s}</span>
            <span className={`text-[10px] px-1.5 py-0.5 rounded ${labelBg} ${labelColor} font-medium`}>
              {dim.label}
            </span>
          </>
        ) : (
          <span className="text-xs text-muted-foreground">-</span>
        )}
      </div>
    </div>
  );
}
