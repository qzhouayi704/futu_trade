// 主力资金 — 信号中心（当日全部 capital_trend 提醒）
// 数据源：GET /api/signals/capital-trends（读 signal_pipeline 中 source='capital_trend'）
//        + WebSocket capital_trend_alert 实时并入（仅当查看今天）

"use client";

import { useState, useEffect, useCallback, useMemo } from "react";
import Link from "next/link";
import { Card } from "@/components/common";
import { useSocket } from "@/lib/socket";
import apiClient from "@/lib/api/client";
import { usePositions } from "../hooks/useDashboard";
import { QuickOrderPopover } from "../components/dashboard/QuickOrderPopover";

interface CapitalTrendSignal {
  stock_code: string;
  stock_name: string;
  direction: "RISING" | "FALLING";
  strength_tier: string;
  strength_mult: number;
  cum_main_net: number;
  window_main_net: number;
  pullback_amount: number;
  intraday_change_pct: number;
  big_buy_count: number;
  big_sell_count: number;
  big_order_threshold: number;
  last_price: number;
  reason: string;
  timestamp: number;
  is_strong_push: boolean;
  // 窗口内买卖强度（2026-07-13 起后端提供；老记录可能没有）
  window_big_buy?: number;
  window_big_sell?: number;
  window_buy_ratio?: number;
  is_held_outflow?: boolean;
  is_large_inflow?: boolean;
  is_hot_candidate?: boolean;
  market_breadth?: number;
  market_universe_size?: number;
  turnover_rank_percentile?: number;
  inflow_gate_reason?: string;
  inflow_stage?: "FIRST" | "SECOND_WATCH" | "CONFIRMED" | "STRENGTHENED" | "EXPIRED" | "REJECTED" | "INVALIDATED" | "WATCH_TRAIL_EXIT" | "TRAIL_EXIT";
  inflow_sequence_no?: number;
  inflow_risk_mode?: "NORMAL" | "WEAK" | "EXTREME";
  plate_name?: string;
  plate_breadth?: number;
  relative_strength_pct?: number;
  inflow_peak_price?: number;
  price_pullback_pct?: number;
  is_inflow_expired?: boolean;
  is_inflow_trailing_exit?: boolean;
  is_watch_trailing_exit?: boolean;
  is_profit_exit?: boolean;
  is_held_outflow_recovery?: boolean;
}

type DirFilter = "all" | "RISING" | "FALLING";

const DIR_FILTERS: { key: DirFilter; label: string; emoji: string }[] = [
  { key: "all", label: "全部", emoji: "💰" },
  { key: "RISING", label: "主力流入", emoji: "📈" },
  { key: "FALLING", label: "主力回落", emoji: "📉" },
];

// 元 → 亿/万
function fmtAmount(v: number): string {
  const abs = Math.abs(v);
  if (abs >= 1e8) return `${(v / 1e8).toFixed(2)}亿`;
  if (abs >= 1e4) return `${(v / 1e4).toFixed(0)}万`;
  return `${v.toFixed(0)}`;
}

function todayStr(): string {
  // sv-SE 本地化即 YYYY-MM-DD，避免 toISOString 的 UTC 偏移
  return new Date().toLocaleDateString("sv-SE");
}

function fmtTime(ts: number): string {
  if (!ts) return "--:--";
  return new Date(ts * 1000).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
}

// 同股同方向同"第几次大单"折叠，保留最新（与信号流卡片同一口径）
function dedupe(list: CapitalTrendSignal[]): CapitalTrendSignal[] {
  const seen = new Set<string>();
  const out: CapitalTrendSignal[] = [];
  for (const s of list) {
    const k = `${s.stock_code}:${s.direction}:${s.inflow_stage ?? ""}:${s.big_buy_count}:${s.big_sell_count}`;
    if (seen.has(k)) continue;
    seen.add(k);
    out.push(s);
  }
  return out;
}

export default function CapitalSignalsPage() {
  const { socket } = useSocket();
  const { data: positions = [] } = usePositions();
  const [signals, setSignals] = useState<CapitalTrendSignal[]>([]);
  const [loading, setLoading] = useState(true);
  const [dateStr, setDateStr] = useState(todayStr());
  const [dir, setDir] = useState<DirFilter>("all");
  const [strongOnly, setStrongOnly] = useState(false);
  const [heldOnly, setHeldOnly] = useState(false);
  const [search, setSearch] = useState("");
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);

  const isToday = dateStr === todayStr();

  const positionSet = useMemo(
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    () => new Set((positions as any[]).map((p) => p.stock_code)),
    [positions]
  );

  const loadSignals = useCallback(async () => {
    try {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const res: any = await apiClient.get(
        `/signals/capital-trends?limit=200&date_str=${dateStr}`
      );
      if (res.success && Array.isArray(res.data)) {
        setSignals(dedupe(res.data));
        setLastUpdate(new Date());
      } else {
        setSignals([]);
      }
    } catch (e) {
      console.error("加载主力资金信号失败:", e);
    } finally {
      setLoading(false);
    }
  }, [dateStr]);

  useEffect(() => {
    setLoading(true);
    loadSignals();
    const timer = setInterval(loadSignals, 120000);
    return () => clearInterval(timer);
  }, [loadSignals]);

  // 实时并入（历史日期不接推送，避免今天的信号混进昨天的列表）
  useEffect(() => {
    if (!socket || !isToday) return;
    const handler = (data: CapitalTrendSignal) => {
      setSignals((prev) => dedupe([data, ...prev]));
      setLastUpdate(new Date());
    };
    socket.on("capital_trend_alert", handler);
    return () => { socket.off("capital_trend_alert", handler); };
  }, [socket, isToday]);

  const filtered = useMemo(() => {
    let list = [...signals];
    if (dir !== "all") list = list.filter((s) => s.direction === dir);
    if (strongOnly) list = list.filter((s) => s.strength_tier === "强");
    if (heldOnly) list = list.filter((s) => positionSet.has(s.stock_code));
    if (search.trim()) {
      const q = search.trim().toLowerCase();
      list = list.filter(
        (s) =>
          s.stock_name?.toLowerCase().includes(q) ||
          s.stock_code.toLowerCase().includes(q)
      );
    }
    return list.sort((a, b) => (b.timestamp || 0) - (a.timestamp || 0));
  }, [signals, dir, strongOnly, heldOnly, search, positionSet]);

  const stats = useMemo(() => {
    const rising = signals.filter((s) => s.direction === "RISING").length;
    const falling = signals.filter((s) => s.direction === "FALLING").length;
    const stockCount = new Set(signals.map((s) => s.stock_code)).size;
    const held = signals.filter((s) => positionSet.has(s.stock_code)).length;
    return { total: signals.length, rising, falling, stockCount, held };
  }, [signals, positionSet]);

  return (
    <div className="container mx-auto px-3 md:px-4 py-4 md:py-6 max-w-7xl">
      {/* 标题栏 */}
      <div className="flex items-center justify-between mb-4 md:mb-6 gap-2 flex-wrap">
        <div className="flex items-center gap-3">
          <Link
            href="/"
            className="flex items-center justify-center w-8 h-8 rounded-lg hover:bg-muted transition-colors"
            title="返回首页"
          >
            <svg className="w-4 h-4 text-muted-foreground" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
            </svg>
          </Link>
          <h1 className="text-xl md:text-2xl font-bold text-foreground flex items-center gap-2">
            <span>💰</span> 主力资金 — 信号中心
          </h1>
        </div>
        <div className="flex items-center gap-2">
          <input
            type="date"
            value={dateStr}
            max={todayStr()}
            onChange={(e) => setDateStr(e.target.value || todayStr())}
            className="text-xs px-2 py-1.5 rounded-lg border border-border bg-background text-foreground"
          />
          <span className="text-[10px] text-muted-foreground">
            {lastUpdate ? `${lastUpdate.toLocaleTimeString("zh-CN")} 更新` : ""}
          </span>
        </div>
      </div>

      {/* 统计条 */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-2 mb-4">
        <Card className="p-3">
          <div className="text-[10px] text-muted-foreground">当日提醒</div>
          <div className="text-lg font-bold text-foreground tabular-nums">{stats.total}</div>
        </Card>
        <Card className="p-3">
          <div className="text-[10px] text-muted-foreground">主力流入 / 回落</div>
          <div className="text-lg font-bold tabular-nums">
            <span className="text-emerald-600 dark:text-emerald-400">{stats.rising}</span>
            <span className="text-muted-foreground mx-1">/</span>
            <span className="text-red-600 dark:text-red-400">{stats.falling}</span>
          </div>
        </Card>
        <Card className="p-3">
          <div className="text-[10px] text-muted-foreground">涉及个股</div>
          <div className="text-lg font-bold text-foreground tabular-nums">{stats.stockCount}</div>
        </Card>
        <Card className="p-3">
          <div className="text-[10px] text-muted-foreground">持仓相关</div>
          <div className="text-lg font-bold text-indigo-600 dark:text-indigo-400 tabular-nums">{stats.held}</div>
        </Card>
      </div>

      {/* 筛选 */}
      <div className="flex items-center gap-2 mb-3 flex-wrap">
        {DIR_FILTERS.map((f) => (
          <button
            key={f.key}
            onClick={() => setDir(f.key)}
            className={`px-3 py-1.5 text-[11px] font-bold rounded-lg transition-all ${
              dir === f.key
                ? "bg-primary text-primary-foreground shadow-sm"
                : "bg-muted/50 text-muted-foreground hover:bg-muted hover:text-foreground"
            }`}
          >
            {f.emoji} {f.label}
          </button>
        ))}
        <button
          onClick={() => setStrongOnly((v) => !v)}
          className={`px-3 py-1.5 text-[11px] font-bold rounded-lg transition-all ${
            strongOnly
              ? "bg-amber-500 text-white shadow-sm"
              : "bg-muted/50 text-muted-foreground hover:bg-muted hover:text-foreground"
          }`}
        >
          🔥 只看强
        </button>
        <button
          onClick={() => setHeldOnly((v) => !v)}
          className={`px-3 py-1.5 text-[11px] font-bold rounded-lg transition-all ${
            heldOnly
              ? "bg-indigo-500 text-white shadow-sm"
              : "bg-muted/50 text-muted-foreground hover:bg-muted hover:text-foreground"
          }`}
        >
          📋 只看持仓
        </button>
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="搜索代码/名称"
          className="text-xs px-2.5 py-1.5 rounded-lg border border-border bg-background text-foreground w-40"
        />
      </div>

      {/* 列表 */}
      <Card className="overflow-hidden">
        <div className="p-3 md:p-4">
          {loading ? (
            <div className="text-center py-10 text-muted-foreground text-sm">
              <div className="w-5 h-5 border-2 border-primary border-t-transparent rounded-full animate-spin mx-auto mb-2" />
              加载中...
            </div>
          ) : filtered.length === 0 ? (
            <div className="text-center py-10 text-muted-foreground text-sm">
              {signals.length === 0 ? "当日暂无主力资金提醒" : "当前筛选条件下无信号"}
            </div>
          ) : (
            <div className="space-y-1.5">
              {filtered.map((sig) => {
                const rising = sig.direction === "RISING";
                const isHeld = positionSet.has(sig.stock_code);
                const trailingExit = sig.is_inflow_trailing_exit === true;
                const outflowRecovery = sig.is_held_outflow_recovery === true;
                const expired = sig.is_inflow_expired === true;
                const confirmed = sig.inflow_stage === "CONFIRMED";
                const strengthened = sig.inflow_stage === "STRENGTHENED";
                const first = sig.inflow_stage === "FIRST";
                const secondWatch = sig.inflow_stage === "SECOND_WATCH";
                const rejected = sig.inflow_stage === "REJECTED";
                const invalidated = sig.inflow_stage === "INVALIDATED";
                const risk = sig.is_held_outflow === true || trailingExit || rejected || invalidated || (!rising && !expired && !outflowRecovery);
                const opportunity = confirmed || strengthened || (rising && !first && !secondWatch && !expired && !outflowRecovery);
                const bg = risk
                  ? "bg-red-50/60 border-red-200/50 dark:bg-red-950/20 dark:border-red-900/30"
                  : opportunity
                  ? "bg-emerald-50/60 border-emerald-200/50 dark:bg-emerald-950/20 dark:border-emerald-900/30"
                  : "bg-slate-50/60 border-slate-200/50 dark:bg-slate-900/20 dark:border-slate-800/40";
                const text = risk
                  ? "text-red-600 dark:text-red-400"
                  : opportunity
                  ? "text-emerald-600 dark:text-emerald-400"
                  : "text-slate-600 dark:text-slate-400";
                const badge = risk
                  ? "bg-red-200/70 text-red-700 dark:bg-red-900/50 dark:text-red-300"
                  : opportunity
                  ? "bg-emerald-200/70 text-emerald-700 dark:bg-emerald-900/50 dark:text-emerald-300"
                  : "bg-slate-200/70 text-slate-700 dark:bg-slate-800/60 dark:text-slate-300";
                const signalLabel = sig.is_held_outflow
                  ? "持仓卖出提醒"
                  : outflowRecovery
                    ? "流出被承接"
                  : trailingExit
                    ? sig.is_watch_trailing_exit ? "试仓回撤退出" : sig.is_profit_exit ? "峰值回撤止盈" : "确认回撤退出"
                    : rejected
                      ? "价格确认失败"
                      : invalidated
                        ? "资金确认失效"
                    : expired
                      ? "流入确认失效"
                      : strengthened
                        ? "资金趋势加强"
                        : confirmed
                          ? "资金买点确认"
                          : secondWatch
                            ? "二次流入观察"
                            : first
                              ? sig.inflow_risk_mode === "WEAK" ? "弱市逆势观察" : "首次流入观察"
                              : rising ? "主力流入" : "主力回落";

                return (
                  <div
                    key={`${sig.stock_code}-${sig.direction}-${sig.inflow_stage ?? ""}-${sig.timestamp}-${sig.big_buy_count}-${sig.big_sell_count}`}
                    className={`px-2.5 py-2 rounded-lg border transition-all hover:shadow-sm ${bg} ${
                      isHeld ? "ring-1 ring-indigo-400/40 dark:ring-indigo-500/30" : ""
                    }`}
                  >
                    {/* 主行 */}
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-1.5 min-w-0 flex-wrap">
                        <span className="text-[10px] font-mono tabular-nums text-muted-foreground shrink-0">
                          {fmtTime(sig.timestamp)}
                        </span>
                        <span className="text-xs">{risk ? "📉" : "📈"}</span>
                        <span className={`font-bold text-xs ${text} truncate`}>{sig.stock_name}</span>
                        <span className="text-[10px] text-muted-foreground shrink-0">{sig.stock_code}</span>
                        <span className={`text-[9px] px-1.5 py-0.5 rounded font-bold shrink-0 ${badge}`}>
                          {signalLabel}·{sig.strength_tier}
                        </span>
                        {isHeld && (
                          <span className="text-[9px] px-1 py-0.5 rounded bg-indigo-100 text-indigo-700 dark:bg-indigo-900/50 dark:text-indigo-300 font-bold shrink-0">
                            持仓
                          </span>
                        )}
                      </div>
                      <div className="flex items-center gap-1.5 shrink-0 ml-2">
                        {sig.last_price > 0 && (
                          <span className="text-xs font-bold tabular-nums text-foreground/70">
                            {sig.last_price.toFixed(3)}
                          </span>
                        )}
                        <span className={`text-xs font-bold tabular-nums ${
                          sig.intraday_change_pct >= 0
                            ? "text-red-600 dark:text-red-400"
                            : "text-green-600 dark:text-green-400"
                        }`}>
                          {sig.intraday_change_pct >= 0 ? "+" : ""}{sig.intraday_change_pct.toFixed(2)}%
                        </span>
                      </div>
                    </div>

                    {/* 资金明细 */}
                    <div className="flex items-center gap-1.5 mt-1 border-t border-dashed border-border/50 pt-1 overflow-x-auto pb-0.5">
                      {/* 买卖强度：让"买方压倒"与"多空对砸净额偏正"一眼可辨 */}
                      {sig.window_big_buy !== undefined && (sig.window_big_buy > 0 || (sig.window_big_sell ?? 0) > 0) && (
                        <span className="text-[8px] px-1 py-0.5 rounded bg-violet-500/10 text-violet-600 dark:text-violet-400 border border-violet-500/20 shrink-0 font-mono">
                          大买 {fmtAmount(sig.window_big_buy)} / 大卖 {fmtAmount(sig.window_big_sell ?? 0)}
                          {sig.window_buy_ratio !== undefined ? ` 买占比${(sig.window_buy_ratio * 100).toFixed(0)}%` : ""}
                        </span>
                      )}
                      {sig.is_hot_candidate && sig.market_breadth !== undefined && (
                        <span className="text-[8px] px-1 py-0.5 rounded bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 border border-emerald-500/20 shrink-0 font-mono">
                          宽度 {(sig.market_breadth * 100).toFixed(0)}%
                          {sig.market_universe_size ? `/${sig.market_universe_size}只` : ""}
                          {sig.turnover_rank_percentile !== undefined
                            ? ` 成交额前${Math.max(0, (1 - sig.turnover_rank_percentile) * 100).toFixed(0)}%`
                            : ""}
                        </span>
                      )}
                      {sig.plate_name && sig.plate_breadth !== undefined && (
                        <span className="text-[8px] px-1 py-0.5 rounded bg-cyan-500/10 text-cyan-700 dark:text-cyan-400 border border-cyan-500/20 shrink-0 font-mono">
                          {sig.inflow_risk_mode ?? "NORMAL"} {sig.plate_name}宽度 {(sig.plate_breadth * 100).toFixed(0)}%
                          {sig.relative_strength_pct !== undefined ? ` 相对+${sig.relative_strength_pct.toFixed(1)}点` : ""}
                        </span>
                      )}
                      <span className="text-[8px] px-1 py-0.5 rounded bg-slate-500/10 text-slate-600 dark:text-slate-300 border border-slate-500/20 shrink-0 font-mono">
                        累计净额 {fmtAmount(sig.cum_main_net)}
                      </span>
                      {sig.pullback_amount > 0 && (
                        <span className="text-[8px] px-1 py-0.5 rounded bg-red-500/10 text-red-600 dark:text-red-400 border border-red-500/20 shrink-0 font-mono">
                          自峰值回落 {fmtAmount(sig.pullback_amount)}
                        </span>
                      )}
                      <span className="text-[8px] px-1 py-0.5 rounded bg-amber-500/10 text-amber-600 dark:text-amber-400 border border-amber-500/20 shrink-0 font-mono">
                        力度 {sig.strength_mult?.toFixed(1)}×
                      </span>
                      <span className="text-[8px] px-1 py-0.5 rounded bg-blue-500/10 text-blue-600 dark:text-blue-400 border border-blue-500/20 shrink-0 font-mono">
                        大单 买{sig.big_buy_count}/卖{sig.big_sell_count}
                      </span>
                      <span className="text-[8px] px-1 py-0.5 rounded bg-cyan-500/10 text-cyan-600 dark:text-cyan-400 border border-cyan-500/20 shrink-0 font-mono">
                        门槛 {fmtAmount(sig.big_order_threshold)}
                      </span>
                    </div>

                    {/* 详情 + 操作 */}
                    <div className="flex items-center justify-between mt-1 gap-2">
                      <span className={`text-[10px] ${text} opacity-75 truncate flex-1`}>
                        {sig.reason}
                      </span>
                      <div className="flex items-center gap-1 shrink-0">
                        <Link
                          href={`/stock-detail?code=${sig.stock_code}&focus=capital-flow`}
                          className="text-[9px] px-1.5 py-0.5 rounded bg-amber-100/80 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300 hover:bg-amber-200 dark:hover:bg-amber-800/50 transition-colors font-medium"
                        >
                          📈净额曲线
                        </Link>
                        <Link
                          href={`/pre-check?code=${sig.stock_code}`}
                          className="text-[9px] px-1.5 py-0.5 rounded bg-blue-100/80 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300 hover:bg-blue-200 dark:hover:bg-blue-800/50 transition-colors font-medium"
                        >
                          ⚡检查
                        </Link>
                        <Link
                          href={`/stock-detail?code=${sig.stock_code}`}
                          className="text-[9px] px-1.5 py-0.5 rounded bg-gray-100/80 text-gray-600 dark:bg-gray-800/50 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-700/50 transition-colors font-medium"
                        >
                          🔍分析
                        </Link>
                        <QuickOrderPopover
                          stockCode={sig.stock_code}
                          stockName={sig.stock_name}
                          price={sig.last_price}
                          direction={rising ? "buy" : "sell"}
                        />
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}

          {!loading && filtered.length > 0 && (
            <div className="flex items-center justify-between mt-3 pt-2 border-t border-border">
              <span className="text-[10px] text-muted-foreground">
                共 {filtered.length} 条{filtered.length !== signals.length ? `（全部 ${signals.length} 条）` : ""}
              </span>
              <Link
                href="/sniper-signals"
                className="text-xs font-medium text-primary hover:text-primary/80 hover:bg-primary/5 px-2 py-1 rounded transition-colors"
              >
                去狙击信号中心 →
              </Link>
            </div>
          )}
        </div>
      </Card>
    </div>
  );
}
