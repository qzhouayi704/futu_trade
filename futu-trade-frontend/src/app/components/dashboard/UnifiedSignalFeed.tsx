// 统一信号流 — 合并狙击信号 + 量价预警 + 信号追踪为一个实时流
// 按紧急度排序：持仓股优先 → 高危信号 → 时间倒序

"use client";

import { useState, useEffect, useCallback, useMemo } from "react";
import Link from "next/link";
import { Card } from "@/components/common";
import { useSocket } from "@/lib/socket";
import apiClient from "@/lib/api/client";
import { QuickOrderPopover } from "./QuickOrderPopover";

// ── 类型定义 ──────────────────────────────────────

interface SniperSignal {
  time: string;
  stock_code: string;
  stock_name: string;
  signal_type: string;
  is_red: boolean;
  emoji: string;
  price: number;
  detail: string;
  action: string;
  severity: string;
}

interface VolumePriceAlert {
  detected: boolean;
  alert_type: "absorption" | "rally" | "dump";
  severity: "high" | "medium";
  position?: "high" | "mid" | "low";
  stock_code: string;
  stock_name: string;
  start_time: string;
  end_time: string;
  duration_min: number;
  price_change_pct: number;
  cum_net_buy: number;
  start_price: number;
  end_price: number;
  message: string;
}

interface PipelineRecord {
  id: number;
  timestamp: string;
  stock_code: string;
  stock_name: string;
  source: string;
  direction: string;
  strength: number;
  final_action: string;
  final_reason: string;
  multi_dimensional_summary?: {
    v1_strength: number;
    v1_label: string;
    v2_score: number;
    momentum_verdict: string;
  };
}

interface MomentumSignal {
  stock_code: string;
  signal_type: string;
  description: string;
  price: number;
  priority: string;
  confidence: number;
  timestamp: number;
  dimensions: string[];
}

// 统一信号项
interface UnifiedSignal {
  id: string;
  source: "v1" | "v2" | "momentum" | "decision";
  time: string;           // HH:MM 格式
  stock_code: string;
  stock_name: string;
  emoji: string;
  label: string;          // 信号类型标签
  detail: string;         // 详情描述
  urgency: number;        // 紧急度 0-100
  is_red: boolean;        // 是否危险信号
  bgColor: string;
  textColor: string;
  badgeColor: string;
  price?: number;
  pricePct?: number;
  multi_dimensional_summary?: {
    v1_strength: number;
    v1_label: string;
    v2_score: number;
    momentum_verdict: string;
  };
}

// ── 信号类型标签 ──────────────────────────────────

const SNIPER_LABELS: Record<string, string> = {
  mega_sell: "巨量砸盘", mega_buy: "巨量抢筹",
  distribution_trap: "出货陷阱", accumulation_signal: "主力吸筹",
};

// distribution_trap / accumulation_signal 已于 2026-06-12 在后端禁用产生（回测显示不如随机），
// 前端不再展示其历史残留，避免高 urgency(90) 的 trap 信号霸占列表。
const PRIMARY_SNIPER_TYPES = new Set(["mega_buy", "mega_sell"]);

// ── Props ──────────────────────────────────────

interface UnifiedSignalFeedProps {
  positionStockCodes?: string[];   // 持仓股票代码列表（用于优先排序）
  maxItems?: number;
  sourceFilter?: "all" | "v1" | "v2" | "momentum" | "decision";  // 信号源筛选
  onSelectStock?: (code: string) => void;
}

export function UnifiedSignalFeed({ positionStockCodes = [], maxItems = 20, sourceFilter = "all", onSelectStock }: UnifiedSignalFeedProps) {
  const { socket } = useSocket();
  const [sniperSignals, setSniperSignals] = useState<SniperSignal[]>([]);
  const [vpAlerts, setVpAlerts] = useState<VolumePriceAlert[]>([]);
  const [pipelineRecords, setPipelineRecords] = useState<PipelineRecord[]>([]);
  const [momentumSignals, setMomentumSignals] = useState<MomentumSignal[]>([]);
  const [loading, setLoading] = useState(true);
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);

  const positionSet = useMemo(() => new Set(positionStockCodes), [positionStockCodes]);

  // ── 数据加载 ──────────────────────────────────

  const loadData = useCallback(async () => {
    try {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const [sigRes, vpRes, pipeRes, momRes]: any[] = await Promise.all([
        apiClient.get("/sniper/signals"),
        apiClient.get("/enhanced-heat/volume-price-alerts?source=all"),
        apiClient.get("/sniper/signal-pipeline?limit=20"),
        apiClient.get("/signals/multi-dimensional/list?limit=15"),
      ]);
      if (sigRes.success && Array.isArray(sigRes.data)) setSniperSignals(sigRes.data);
      if (vpRes.success && Array.isArray(vpRes.data)) setVpAlerts(vpRes.data);
      if (pipeRes.success && Array.isArray(pipeRes.data)) setPipelineRecords(pipeRes.data);
      
      // 解析多维列表中的动量信号作为初始动量数据
      if (momRes.success && momRes.data && Array.isArray(momRes.data.list)) {
        const list: MomentumSignal[] = [];
        for (const item of momRes.data.list) {
          if (item.momentum_engine) {
            list.push({
              stock_code: item.stock_code,
              signal_type: item.momentum_engine.verdict,
              description: `动量爆发: ${item.momentum_engine.dimensions?.join('+') || '多维'}`,
              price: item.current_price,
              priority: item.momentum_engine.verdict.startsWith('STRONG') ? 'HIGH' : 'MEDIUM',
              confidence: 0.8,
              timestamp: Math.round(Date.now() / 1000),
              dimensions: item.momentum_engine.dimensions || []
            });
          }
        }
        setMomentumSignals(list);
      }
      setLastUpdate(new Date());
    } catch (e) {
      console.error("加载信号数据失败:", e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData();
    const timer = setInterval(loadData, 120000);
    return () => clearInterval(timer);
  }, [loadData]);

  // ── WebSocket 实时信号 ──────────────────────────

  useEffect(() => {
    if (!socket) return;

    const handleSniper = (data: SniperSignal) => {
      setSniperSignals(prev => {
        const updated = [data, ...prev];
        const seen = new Set<string>();
        return updated.filter(s => {
          const key = `${s.stock_code}:${s.signal_type}:${s.time}`;
          if (seen.has(key)) return false;
          seen.add(key);
          return true;
        });
      });
      setLastUpdate(new Date());
    };

    const handlePipeline = (data: PipelineRecord) => {
      setPipelineRecords(prev => [data, ...prev].slice(0, 50));
      setLastUpdate(new Date());
    };

    const handleMomentum = (data: MomentumSignal) => {
      setMomentumSignals(prev => {
        const updated = [data, ...prev];
        const seen = new Set<string>();
        return updated.filter(s => {
          const key = `${s.stock_code}:${s.signal_type}:${s.timestamp}`;
          if (seen.has(key)) return false;
          seen.add(key);
          return true;
        });
      });
      setLastUpdate(new Date());
    };

    socket.on("sniper_signal", handleSniper);
    socket.on("signal_pipeline", handlePipeline);
    socket.on("momentum_signal", handleMomentum);
    return () => {
      socket.off("sniper_signal", handleSniper);
      socket.off("signal_pipeline", handlePipeline);
      socket.off("momentum_signal", handleMomentum);
    };
  }, [socket]);

  // ── 转换为统一信号格式 ──────────────────────────

  const unifiedSignals = useMemo((): UnifiedSignal[] => {
    const items: UnifiedSignal[] = [];

    // 1. V1 Sniper（仅 mega_buy / mega_sell，见 PRIMARY_SNIPER_TYPES）
    for (const sig of sniperSignals) {
      if (!PRIMARY_SNIPER_TYPES.has(sig.signal_type)) continue;

      const isBuy = sig.signal_type === "mega_buy";

      let bgColor: string, textColor: string, badgeColor: string;
      if (sig.is_red) {
        bgColor = "bg-red-50/60 border-red-200/50 dark:bg-red-950/20 dark:border-red-900/30";
        textColor = "text-red-600 dark:text-red-400";
        badgeColor = "bg-red-200/70 text-red-700 dark:bg-red-900/50 dark:text-red-300";
      } else {
        bgColor = "bg-emerald-50/60 border-emerald-200/50 dark:bg-emerald-950/20 dark:border-emerald-900/30";
        textColor = "text-emerald-600 dark:text-emerald-400";
        badgeColor = "bg-emerald-200/70 text-emerald-700 dark:bg-emerald-900/50 dark:text-emerald-300";
      }

      items.push({
        id: `v1-${sig.stock_code}-${sig.signal_type}-${sig.time}`,
        source: "v1",
        time: sig.time,
        stock_code: sig.stock_code,
        stock_name: sig.stock_name,
        emoji: sig.emoji,
        label: SNIPER_LABELS[sig.signal_type] || sig.signal_type,
        detail: sig.detail,
        urgency: sig.is_red ? 85 : isBuy ? 80 : 70,
        is_red: sig.is_red,
        bgColor, textColor, badgeColor,
        price: sig.price,
      });
    }

    // 2. V2 Scorer
    for (const alert of vpAlerts) {
      const isAbsorption = alert.alert_type === "absorption";
      const isDump = alert.alert_type === "dump";
      const isHigh = alert.severity === "high";

      let emoji: string, label: string, bgColor: string, textColor: string, badgeColor: string;

      if (isAbsorption) {
        emoji = isHigh ? "🚨" : "⚠️";
        label = "买入吸收";
        bgColor = isHigh
          ? "bg-red-50/80 border-red-200/60 dark:bg-red-950/20 dark:border-red-800/40"
          : "bg-orange-50/80 border-orange-200/60 dark:bg-orange-950/20 dark:border-orange-800/40";
        textColor = isHigh ? "text-red-600 dark:text-red-400" : "text-orange-600 dark:text-orange-400";
        badgeColor = isHigh ? "bg-red-200/80 text-red-700" : "bg-orange-200/80 text-orange-700";
      } else if (isDump) {
        emoji = "💥";
        label = "放量下跌";
        bgColor = "bg-purple-50/80 border-purple-200/60 dark:bg-purple-950/20 dark:border-purple-800/40";
        textColor = "text-purple-600 dark:text-purple-400";
        badgeColor = "bg-purple-200/80 text-purple-700";
      } else {
        const pos = alert.position;
        emoji = pos === "low" ? "🚀" : pos === "high" ? "⚡" : "📈";
        label = pos === "low" ? "低位拉升" : pos === "high" ? "高位拉升" : "拉升";
        bgColor = pos === "low"
          ? "bg-emerald-50/80 border-emerald-200/60 dark:bg-emerald-950/20 dark:border-emerald-800/40"
          : "bg-blue-50/80 border-blue-200/60 dark:bg-blue-950/20 dark:border-blue-800/40";
        textColor = pos === "low"
          ? "text-emerald-600 dark:text-emerald-400"
          : "text-blue-600 dark:text-blue-400";
        badgeColor = pos === "low"
          ? "bg-emerald-200/80 text-emerald-700"
          : "bg-blue-200/80 text-blue-700";
      }

      items.push({
        id: `v2-${alert.stock_code}-${alert.alert_type}-${alert.start_time}`,
        source: "v2",
        time: alert.end_time,
        stock_code: alert.stock_code,
        stock_name: alert.stock_name,
        emoji, label,
        detail: `${alert.start_time}~${alert.end_time} ${alert.duration_min}分钟 ${alert.price_change_pct >= 0 ? "+" : ""}${alert.price_change_pct.toFixed(2)}%`,
        urgency: isAbsorption ? (isHigh ? 88 : 65) : isDump ? 82 : 60,
        is_red: isAbsorption || isDump,
        bgColor, textColor, badgeColor,
        pricePct: alert.price_change_pct,
      });
    }

    // 3. 动量引擎
    for (const sig of momentumSignals) {
      const isBuy = sig.signal_type.includes("BUY");
      const timeStr = sig.timestamp
        ? new Date(sig.timestamp * 1000).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })
        : new Date().toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });

      items.push({
        id: `momentum-${sig.stock_code}-${sig.signal_type}-${sig.timestamp}`,
        source: "momentum",
        time: timeStr,
        stock_code: sig.stock_code,
        stock_name: sig.stock_code,
        emoji: "⚡",
        label: sig.signal_type,
        detail: sig.description,
        urgency: sig.priority === "HIGH" ? 85 : 65,
        is_red: !isBuy,
        bgColor: isBuy
          ? "bg-cyan-50/60 border-cyan-200/50 dark:bg-cyan-950/20 dark:border-cyan-900/30"
          : "bg-rose-50/40 border-rose-200/40 dark:bg-rose-950/20 dark:border-rose-900/30",
        textColor: isBuy ? "text-cyan-600 dark:text-cyan-400" : "text-rose-600 dark:text-rose-400",
        badgeColor: isBuy ? "bg-cyan-200/70 text-cyan-700" : "bg-rose-200/70 text-rose-700",
        price: sig.price,
      });
    }

    // 4. 决策/策略流水
    for (const rec of pipelineRecords) {
      if (rec.final_action !== "executed" && rec.final_action !== "broadcast") continue;
      const isBroadcast = rec.final_action === "broadcast";
      const isBuy = rec.direction === "BUY";
      items.push({
        id: `decision-${rec.id || rec.timestamp}`,
        source: "decision",
        time: rec.timestamp?.slice(11, 16) || "",
        stock_code: rec.stock_code,
        stock_name: rec.stock_name,
        emoji: isBroadcast ? "📡" : isBuy ? "✅" : "🔻",
        label: isBroadcast
          ? `${isBuy ? "买入机会" : rec.direction === "SELL" ? "防守触发" : "风险预警"}`
          : `策略${isBuy ? "买入" : "卖出"}`,
        detail: rec.final_reason,
        urgency: isBroadcast ? 55 : 50,
        is_red: !isBuy,
        bgColor: isBuy
          ? "bg-emerald-50/60 border-emerald-200/50 dark:bg-emerald-950/20 dark:border-emerald-900/30"
          : "bg-red-50/40 border-red-200/40 dark:bg-red-950/20 dark:border-red-900/30",
        textColor: isBuy
          ? "text-emerald-600 dark:text-emerald-400"
          : "text-red-600 dark:text-red-400",
        badgeColor: isBuy
          ? "bg-emerald-200/70 text-emerald-700"
          : "bg-red-200/70 text-red-700",
        multi_dimensional_summary: rec.multi_dimensional_summary
      });
    }

    // 排序：持仓股优先 → 紧急度 → 时间倒序
    items.sort((a, b) => {
      const aPos = positionSet.has(a.stock_code) ? 1 : 0;
      const bPos = positionSet.has(b.stock_code) ? 1 : 0;
      if (aPos !== bPos) return bPos - aPos;
      if (a.urgency !== b.urgency) return b.urgency - a.urgency;
      return b.time.localeCompare(a.time);
    });

    // 按 source 筛选
    const filtered = sourceFilter && sourceFilter !== "all"
      ? items.filter(s => s.source === sourceFilter)
      : items;

    // 每股条数上限：防止单只股票（尤其持仓股）的高频信号霸占整个列表，
    // 挤掉其他股票的信号。已排序，故保留的是每只股票 urgency/时间最高的若干条。
    const MAX_PER_STOCK = 3;
    const perStockCount = new Map<string, number>();
    const capped: UnifiedSignal[] = [];
    for (const sig of filtered) {
      const n = perStockCount.get(sig.stock_code) ?? 0;
      if (n >= MAX_PER_STOCK) continue;
      perStockCount.set(sig.stock_code, n + 1);
      capped.push(sig);
    }

    return capped.slice(0, maxItems);
  }, [sniperSignals, vpAlerts, pipelineRecords, momentumSignals, positionSet, maxItems, sourceFilter]);

  // ── 统计 ──────────────────────────────────

  const stats = useMemo(() => {
    const danger = unifiedSignals.filter(s => s.urgency >= 80).length;
    const opportunity = unifiedSignals.filter(s => !s.is_red && s.urgency >= 60).length;
    const posRelated = unifiedSignals.filter(s => positionSet.has(s.stock_code)).length;
    return { total: unifiedSignals.length, danger, opportunity, posRelated };
  }, [unifiedSignals, positionSet]);

  // ── 渲染 ──────────────────────────────────

  return (
    <Card className="overflow-hidden">
      <div className="p-4 md:p-5">
        {/* 标题栏 */}
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-base font-semibold text-foreground flex items-center gap-1.5">
            <span className="text-base">🚨</span>
            实时信号流
          </h3>
          <div className="flex items-center gap-2">
            {stats.posRelated > 0 && (
              <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-indigo-100 text-indigo-700 dark:bg-indigo-950/40 dark:text-indigo-400 font-bold animate-pulse">
                📋 {stats.posRelated} 持仓相关
              </span>
            )}
            {stats.danger > 0 && (
              <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-red-100 text-red-700 dark:bg-red-950/40 dark:text-red-400 font-medium">
                🔴 {stats.danger}
              </span>
            )}
            {stats.opportunity > 0 && (
              <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-emerald-100 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-400 font-medium">
                🟢 {stats.opportunity}
              </span>
            )}
            <span className="text-[10px] text-muted-foreground">
              {lastUpdate ? lastUpdate.toLocaleTimeString("zh-CN") : ""}
            </span>
          </div>
        </div>

        {loading ? (
          <div className="text-center py-8 text-muted-foreground text-sm">
            <div className="w-5 h-5 border-2 border-primary border-t-transparent rounded-full animate-spin mx-auto mb-2" />
            信号扫描中...
          </div>
        ) : unifiedSignals.length === 0 ? (
          <div className="text-center py-8 text-muted-foreground text-sm">
            暂无活跃信号 — 系统持续监控中
          </div>
        ) : (
          <div className="space-y-1.5 max-h-[520px] overflow-y-auto pr-1
                        [&::-webkit-scrollbar]:w-1 [&::-webkit-scrollbar-thumb]:rounded-full
                        [&::-webkit-scrollbar-thumb]:bg-gray-300 dark:[&::-webkit-scrollbar-thumb]:bg-gray-600">
            {unifiedSignals.map((sig) => {
              const isPositionStock = positionSet.has(sig.stock_code);

              return (
                <div
                  key={sig.id}
                  className={`px-2.5 py-2 rounded-lg border transition-all hover:shadow-sm ${sig.bgColor} ${
                    isPositionStock ? "ring-1 ring-indigo-400/40 dark:ring-indigo-500/30" : ""
                  }`}
                >
                  {/* 主行 */}
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-1.5 min-w-0 flex-wrap">
                      <span className="text-[10px] font-mono tabular-nums text-muted-foreground shrink-0">
                        {sig.time}
                      </span>
                      <span className={`text-xs ${sig.urgency >= 80 ? "animate-pulse" : ""}`}>
                        {sig.emoji}
                      </span>
                      <span className={`font-bold text-xs ${sig.textColor} truncate`}>
                        {sig.stock_name}
                      </span>
                      <span className="text-[10px] text-muted-foreground shrink-0">
                        {sig.stock_code}
                      </span>
                      <span className={`text-[9px] px-1.5 py-0.5 rounded font-bold shrink-0 ${sig.badgeColor}`}>
                        {sig.label}
                      </span>
                      {isPositionStock && (
                        <span className="text-[9px] px-1 py-0.5 rounded bg-indigo-100 text-indigo-700 dark:bg-indigo-900/50 dark:text-indigo-300 font-bold shrink-0">
                          持仓
                        </span>
                      )}
                    </div>
                    <div className="flex items-center gap-1.5 shrink-0 ml-2">
                      {sig.price && (
                        <span className="text-xs font-bold tabular-nums text-foreground/70">
                          {sig.price.toFixed(3)}
                        </span>
                      )}
                      {sig.pricePct !== undefined && (
                        <span className={`text-xs font-bold tabular-nums ${
                          sig.pricePct >= 0 ? "text-red-600 dark:text-red-400" : "text-green-600 dark:text-green-400"
                        }`}>
                          {sig.pricePct >= 0 ? "+" : ""}{sig.pricePct.toFixed(2)}%
                        </span>
                      )}
                    </div>
                  </div>

                  {/* 多维证据微型面板 */}
                  {sig.multi_dimensional_summary && (
                    <div className="flex items-center gap-1.5 mt-1 border-t border-dashed border-border/50 pt-1 overflow-x-auto pb-0.5">
                      <span className="text-[9px] text-slate-500 dark:text-slate-400 shrink-0 font-medium">多维证据:</span>
                      {sig.multi_dimensional_summary.v1_strength > 0 && (
                        <span className="text-[8px] px-1 py-0.5 rounded bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border border-emerald-500/20 shrink-0 font-mono">
                          V1:{sig.multi_dimensional_summary.v1_label}({sig.multi_dimensional_summary.v1_strength})
                        </span>
                      )}
                      {sig.multi_dimensional_summary.v2_score > 0 && (
                        <span className="text-[8px] px-1 py-0.5 rounded bg-blue-500/10 text-blue-600 dark:text-blue-400 border border-blue-500/20 shrink-0 font-mono">
                          V2:{sig.multi_dimensional_summary.v2_score}分
                        </span>
                      )}
                      {sig.multi_dimensional_summary.momentum_verdict && sig.multi_dimensional_summary.momentum_verdict !== 'WATCH' && (
                        <span className="text-[8px] px-1 py-0.5 rounded bg-cyan-500/10 text-cyan-600 dark:text-cyan-400 border border-cyan-500/20 shrink-0 font-mono">
                          动量:{sig.multi_dimensional_summary.momentum_verdict}
                        </span>
                      )}
                    </div>
                  )}

                  {/* 详情 + 操作按钮 */}
                  <div className="flex items-center justify-between mt-1 gap-2">
                    <span className={`text-[10px] ${sig.textColor} opacity-75 truncate flex-1`}>
                      {sig.detail}
                    </span>
                    <div className="flex items-center gap-1 shrink-0">
                      {onSelectStock && (
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            onSelectStock(sig.stock_code);
                          }}
                          className="text-[9px] px-1.5 py-0.5 rounded bg-indigo-100/80 text-indigo-700 dark:bg-indigo-900/40 dark:text-indigo-300 hover:bg-indigo-200 dark:hover:bg-indigo-800/50 transition-colors font-medium"
                        >
                          📊多维
                        </button>
                      )}
                      <Link
                        href={`/pre-check?code=${sig.stock_code}`}
                        onClick={(e) => { e.stopPropagation(); }}
                        className="text-[9px] px-1.5 py-0.5 rounded bg-blue-100/80 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300 hover:bg-blue-200 dark:hover:bg-blue-800/50 transition-colors font-medium"
                      >
                        ⚡检查
                      </Link>
                      <Link
                        href={`/stock-detail?code=${sig.stock_code}`}
                        onClick={(e) => { e.stopPropagation(); }}
                        className="text-[9px] px-1.5 py-0.5 rounded bg-gray-100/80 text-gray-600 dark:bg-gray-800/50 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-700/50 transition-colors font-medium"
                      >
                        🔍分析
                      </Link>
                      <QuickOrderPopover
                        stockCode={sig.stock_code}
                        stockName={sig.stock_name}
                        price={sig.price}
                        direction={sig.is_red ? "sell" : "buy"}
                      />
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {/* 底部：查看全部 */}
        {unifiedSignals.length > 0 && (
          <div className="flex items-center justify-between mt-3 pt-2 border-t border-border">
            <span className="text-[10px] text-muted-foreground">
              共 {stats.total} 条信号
            </span>
            <Link
              href="/sniper-signals"
              className="text-xs font-medium text-primary hover:text-primary/80 hover:bg-primary/5 px-2 py-1 rounded transition-colors flex items-center gap-1"
            >
              查看全部信号
              <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
              </svg>
            </Link>
          </div>
        )}
      </div>
    </Card>
  );
}
