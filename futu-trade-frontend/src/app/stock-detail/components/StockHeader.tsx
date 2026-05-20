// 个股头部 — 价格/涨跌/标签/最佳策略摘要
"use client";

import type { TopHotStock } from "@/types";

interface Props {
  stock: TopHotStock | null;
  loading?: boolean;
}

export default function StockHeader({ stock, loading }: Props) {
  if (loading) {
    return (
      <div className="animate-pulse flex items-center gap-6 p-6 bg-card rounded-xl border border-border">
        <div className="h-8 w-32 bg-muted rounded" />
        <div className="h-10 w-24 bg-muted rounded" />
        <div className="h-6 w-48 bg-muted rounded" />
      </div>
    );
  }

  if (!stock) return null;

  const changeRate = stock.change_rate ?? 0;
  const isUp = changeRate > 0;
  const isDown = changeRate < 0;
  const colorClass = isUp ? "text-red-500" : isDown ? "text-green-500" : "text-foreground";
  const bgAccent = isUp ? "bg-red-500/10" : isDown ? "bg-green-500/10" : "bg-muted";

  const consensus = stock.consensus;
  const bestMode = consensus?.best_mode || "TREND";
  const bestScore = consensus?.total_score ?? 0;
  const passed = consensus?.passed ?? false;
  const veto = consensus?.veto_reason;

  const modeLabels: Record<string, { emoji: string; label: string }> = {
    TREND: { emoji: "📈", label: "趋势策略" },
    BREAKOUT: { emoji: "🔺", label: "蓄势突破" },
    MOMENTUM: { emoji: "🚀", label: "动量接力" },
  };
  const bestModeInfo = modeLabels[bestMode] || modeLabels.TREND;

  const scoreColor = bestScore >= 60
    ? "text-green-600 bg-green-500/15 border-green-500/30"
    : bestScore >= 40
    ? "text-amber-600 bg-amber-500/15 border-amber-500/30"
    : "text-red-500 bg-red-500/15 border-red-500/30";

  return (
    <div className="p-5 bg-card rounded-xl border border-border">
      <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
        {/* 股票代码和名称 */}
        <div className="flex items-baseline gap-2">
          <h2 className="text-2xl font-bold text-foreground tracking-tight">{stock.name}</h2>
          <span className="text-sm text-muted-foreground font-mono">{stock.code}</span>
        </div>

        {/* 价格和涨跌 */}
        <div className="flex items-baseline gap-3">
          <span className={`text-3xl font-bold tabular-nums ${colorClass}`}>
            {stock.cur_price?.toFixed(3)}
          </span>
          <span className={`text-lg font-semibold tabular-nums px-2 py-0.5 rounded ${bgAccent} ${colorClass}`}>
            {isUp ? "+" : ""}{changeRate.toFixed(2)}%
          </span>
        </div>

        {/* 板块标签 */}
        <div className="flex flex-wrap gap-1.5">
          {stock.plates?.slice(0, 3).map((p) => (
            <span key={p.plate_code} className="px-2 py-0.5 text-xs rounded-full bg-blue-500/10 text-blue-600 border border-blue-500/20">
              {p.plate_name}
            </span>
          ))}
        </div>

        {/* 风控标签 */}
        {stock.stock_tag && (
          <span className="px-2 py-0.5 text-xs rounded-full bg-orange-500/10 text-orange-600 border border-orange-500/20">
            {stock.stock_tag.label} · {stock.stock_tag.phase}
          </span>
        )}

        {/* 最佳策略徽章 — 推到右侧 */}
        <div className="ml-auto flex items-center gap-3">
          {veto && (
            <span className="text-xs text-red-500 bg-red-500/10 px-2 py-1 rounded border border-red-500/20">
              ⛔ {veto}
            </span>
          )}
          <div className={`flex items-center gap-2 px-3 py-1.5 rounded-lg border ${scoreColor}`}>
            <span className="text-sm">{bestModeInfo.emoji}</span>
            <span className="text-sm font-medium">{bestModeInfo.label}</span>
            <span className="text-lg font-bold tabular-nums">{bestScore}</span>
            <span className="text-xs">/100</span>
            {passed && <span className="text-green-600 text-sm">✅</span>}
          </div>
        </div>
      </div>

      {/* 第二行：关键数字 */}
      <div className="flex flex-wrap gap-x-5 gap-y-1 mt-3 text-xs text-muted-foreground">
        <span>开盘 <b className="text-foreground">{stock.open_price?.toFixed(3)}</b></span>
        <span>最高 <b className="text-red-500">{stock.high_price?.toFixed(3)}</b></span>
        <span>最低 <b className="text-green-500">{stock.low_price?.toFixed(3)}</b></span>
        <span>昨收 <b className="text-foreground">{stock.prev_close_price?.toFixed(3)}</b></span>
        <span>成交额 <b className="text-foreground">{formatTurnover(stock.turnover)}</b></span>
        <span>换手 <b className="text-foreground">{stock.turnover_rate?.toFixed(2)}%</b></span>
        <span>振幅 <b className="text-foreground">{stock.amplitude?.toFixed(2)}%</b></span>
        <span>量比 <b className="text-foreground">{stock.volume_ratio?.toFixed(2) || "-"}</b></span>
      </div>
    </div>
  );
}

function formatTurnover(v: number): string {
  if (!v) return "-";
  if (v >= 1e8) return (v / 1e8).toFixed(2) + "亿";
  if (v >= 1e4) return (v / 1e4).toFixed(0) + "万";
  return v.toFixed(0);
}
