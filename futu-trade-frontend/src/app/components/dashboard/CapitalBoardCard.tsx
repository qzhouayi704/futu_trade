// 主力资金看板 — 以股票为中心的资金强度排行（只留真大单）
// 全监控/订阅池 ∪ 持仓，按累计净额排名；行内并入 V1 Sniper 信号，资金流入+狙击共振高亮。
// API 轮询(180s) + WebSocket(sniper_signal / capital_trend_alert) 局部行更新。

"use client";

import { useState, useEffect, useCallback } from "react";
import { Card } from "@/components/common";
import { useSocket } from "@/lib/socket";
import { capitalBoardApi } from "@/lib/api/capital-board";
import type { CapitalBoardRow, CapitalBoardSniperSig } from "@/types/capital-board";

const BUY_SNIPER_TYPES = new Set(["mega_buy", "accel_in", "reversal_bull"]);

// 方向 → 文案 + 配色（买入绿 / 风险红 / 观察灰）
const DIRECTION_META: Record<string, { label: string; bucket: "buy" | "risk" | "watch" }> = {
  inflow: { label: "主力流入", bucket: "buy" },
  outflow: { label: "主力流出", bucket: "risk" },
  pullback: { label: "主力回落", bucket: "risk" },
  distribution: { label: "拉高出货", bucket: "risk" },
  flat: { label: "主力持平", bucket: "watch" },
};

const BUCKET_STYLE = {
  buy: { row: "bg-emerald-50/60 border-emerald-200/50", text: "text-emerald-600", badge: "bg-emerald-200/70 text-emerald-700" },
  risk: { row: "bg-red-50/60 border-red-200/50", text: "text-red-600", badge: "bg-red-200/70 text-red-700" },
  watch: { row: "bg-slate-50/60 border-slate-200/50", text: "text-slate-600", badge: "bg-slate-200/70 text-slate-600" },
};

const SNIPER_LABELS: Record<string, string> = {
  mega_buy: "巨量抢筹", mega_sell: "巨量砸盘",
  reversal_bull: "资金转正", reversal_bear: "资金转负",
  accel_in: "资金加速", sustained_out: "持续流出",
};

function fmtAmount(v: number | null): string {
  if (v == null) return "—";
  const a = Math.abs(v);
  const sign = v > 0 ? "+" : v < 0 ? "-" : "";
  if (a >= 1e8) return `${sign}${(a / 1e8).toFixed(2)}亿`;
  if (a >= 1e4) return `${sign}${(a / 1e4).toFixed(0)}万`;
  return `${sign}${a.toFixed(0)}`;
}

function rowHasBuySniper(sigs: CapitalBoardSniperSig[]): boolean {
  return sigs.some((s) => BUY_SNIPER_TYPES.has(s.signal_type));
}

interface Props {
  onSelectStock?: (code: string) => void;
}

export function CapitalBoardCard({ onSelectStock }: Props) {
  const { socket } = useSocket();
  const [rows, setRows] = useState<CapitalBoardRow[]>([]);
  const [poolSize, setPoolSize] = useState(0);
  const [bigCount, setBigCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);

  const loadData = useCallback(async () => {
    try {
      const res = await capitalBoardApi.getRanking(20, true);
      if (res.success && res.data) {
        const d = res.data as { ranking: CapitalBoardRow[]; pool_size: number; big_order_count: number };
        setRows(Array.isArray(d.ranking) ? d.ranking : []);
        setPoolSize(d.pool_size || 0);
        setBigCount(d.big_order_count || 0);
      }
      setLastUpdate(new Date());
    } catch (e) {
      console.error("加载主力资金看板失败:", e);
    } finally {
      setLoading(false);
    }
  }, []);

  // 初始 + 180s 轮询（整卡重排只在轮询时发生，避免抖动）
  useEffect(() => {
    loadData();
    const timer = setInterval(loadData, 180000);
    return () => clearInterval(timer);
  }, [loadData]);

  // WebSocket：sniper_signal 局部点亮对应行；capital_trend_alert 更新资金态
  useEffect(() => {
    if (!socket) return;

    const onSniper = (data: CapitalBoardSniperSig & { stock_code: string }) => {
      if (!data?.stock_code) return;
      setRows((prev) => {
        let changed = false;
        const next = prev.map((r) => {
          if (r.stock_code !== data.stock_code) return r;
          changed = true;
          const slim: CapitalBoardSniperSig = {
            signal_type: data.signal_type, strength: data.strength || 0,
            tier: data.tier || "", time: data.time, is_red: !!data.is_red, emoji: data.emoji || "",
          };
          const key = (s: CapitalBoardSniperSig) => `${s.signal_type}:${s.time}`;
          const seen = new Set([key(slim)]);
          const merged = [slim, ...r.sniper_signals.filter((s) => !seen.has(key(s)))];
          const dirMeta = DIRECTION_META[r.direction];
          const resonance = dirMeta?.bucket === "buy"
            && (r.strength === "强" || r.strength === "中")
            && rowHasBuySniper(merged);
          return { ...r, sniper_signals: merged, is_resonance: resonance };
        });
        return changed ? next : prev;
      });
    };

    const onCapitalTrend = (a: { stock_code: string; direction: string; strength_tier: string; strength_mult: number }) => {
      if (!a?.stock_code) return;
      const dir = a.direction === "RISING" ? "inflow"
        : a.direction === "FALLING" ? "pullback" : null;
      if (!dir) return;
      setRows((prev) => prev.map((r) =>
        r.stock_code === a.stock_code
          ? { ...r, direction: dir, strength: a.strength_tier || r.strength, strength_mult: a.strength_mult ?? r.strength_mult }
          : r));
    };

    socket.on("sniper_signal", onSniper);
    socket.on("capital_trend_alert", onCapitalTrend);
    return () => {
      socket.off("sniper_signal", onSniper);
      socket.off("capital_trend_alert", onCapitalTrend);
    };
  }, [socket]);

  return (
    <Card>
      <div className="p-4 md:p-5">
        {/* 标题栏 */}
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-base font-semibold text-gray-900 flex items-center gap-1.5">
            <span className="text-base">💰</span>
            主力资金看板
            {bigCount > 0 && (
              <span className="text-[10px] font-normal text-gray-400">
                · 真大单 {bigCount} 只 / 监控 {poolSize}
              </span>
            )}
          </h3>
          <span className="text-[10px] text-gray-400">
            {lastUpdate ? `${lastUpdate.toLocaleTimeString("zh-CN")} 更新` : ""}
          </span>
        </div>

        {loading ? (
          <div className="text-center py-6 text-gray-400 text-sm">扫描中...</div>
        ) : rows.length === 0 ? (
          <div className="text-center py-4 text-gray-400 text-sm">
            暂无达标大单 — 主力资金未现明显大单动向
          </div>
        ) : (
          <div className="space-y-1">
            {rows.map((r, idx) => {
              const meta = DIRECTION_META[r.direction] || DIRECTION_META.flat;
              const style = BUCKET_STYLE[meta.bucket];
              const buySigs = r.sniper_signals.filter((s) => BUY_SNIPER_TYPES.has(s.signal_type));
              const showSigs = (buySigs.length ? buySigs : r.sniper_signals).slice(0, 2);
              const extra = r.sniper_signals.length - showSigs.length;
              return (
                <div
                  key={r.stock_code}
                  onClick={() => onSelectStock?.(r.stock_code)}
                  className={`px-2 py-1.5 rounded-lg border cursor-pointer transition-colors hover:brightness-[0.98] ${style.row} ${
                    r.is_resonance ? "ring-1 ring-amber-300/70" : ""
                  }`}
                >
                  <div className="flex items-center justify-between gap-2">
                    {/* 左：序号 + 名称 + 资金态 + 行内 sniper */}
                    <div className="flex items-center gap-1.5 min-w-0">
                      <span className="text-[10px] font-bold text-gray-400 w-3 shrink-0">{idx + 1}</span>
                      <span className="font-bold text-xs text-gray-800 truncate">{r.stock_name}</span>
                      {r.held && (
                        <span className="text-[8px] px-1 py-px rounded bg-indigo-200/70 text-indigo-700 font-bold shrink-0">持</span>
                      )}
                      <span className={`text-[9px] px-1 py-px rounded font-medium shrink-0 ${style.badge}`}>
                        {meta.label}·{r.strength}
                      </span>
                      {r.flow_source === "cache" && (
                        <span className="text-[8px] px-1 py-px rounded bg-gray-100 text-gray-400 shrink-0" title="逐笔口径暂无数据，回退富途聚合口径">富途口径</span>
                      )}
                      {r.is_resonance && (
                        <span className="text-[8px] px-1 py-px rounded bg-amber-200/80 text-amber-800 font-bold shrink-0">共振</span>
                      )}
                      {showSigs.map((s, i) => (
                        <span
                          key={`${s.signal_type}-${s.time}-${i}`}
                          className={`text-[8px] px-1 py-px rounded font-medium shrink-0 ${
                            s.is_red ? "bg-red-100 text-red-600" : "bg-sky-100 text-sky-700"
                          }`}
                        >
                          {SNIPER_LABELS[s.signal_type] || s.signal_type}
                        </span>
                      ))}
                      {extra > 0 && (
                        <span className="text-[8px] text-gray-400 shrink-0">×{extra + showSigs.length}</span>
                      )}
                      {r.sniper_only && (
                        <span className="text-[8px] px-1 py-px rounded bg-gray-100 text-gray-400 shrink-0" title="净额未达大单门槛，仅 Sniper 信号入榜">仅狙击</span>
                      )}
                    </div>
                    {/* 右：价格 + 涨跌 */}
                    <div className="flex items-center gap-2 shrink-0">
                      <span className="text-xs font-bold tabular-nums text-gray-700">{r.last_price.toFixed(3)}</span>
                      <span className={`text-[11px] font-bold tabular-nums w-14 text-right ${r.intraday_pct >= 0 ? "text-red-500" : "text-green-600"}`}>
                        {r.intraday_pct >= 0 ? "+" : ""}{r.intraday_pct.toFixed(2)}%
                      </span>
                    </div>
                  </div>
                  {/* 第二行：累计净额 + 力度 + 大单次数 */}
                  <div className="flex items-center gap-2 mt-0.5 text-[10px] text-gray-500">
                    <span className={`font-medium tabular-nums ${style.text}`}>
                      净额 {fmtAmount(r.net_amount)}
                    </span>
                    {r.strength_mult != null && r.strength_mult > 0 && (
                      <span className="tabular-nums">力度 ×{r.strength_mult.toFixed(1)}</span>
                    )}
                    {r.big_buy_count > 0 && (
                      <span className="text-emerald-600/80">大单买 {r.big_buy_count}</span>
                    )}
                    {r.big_sell_count > 0 && (
                      <span className="text-red-500/80">大单卖 {r.big_sell_count}</span>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </Card>
  );
}
