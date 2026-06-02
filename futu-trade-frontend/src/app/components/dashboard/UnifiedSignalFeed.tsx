// 统一信号流 — 合并狙击信号 + 量价预警 + 信号追踪为一个实时流
// 按紧急度排序：持仓股优先 → 高危信号 → 时间倒序

"use client";

import { useState, useEffect, useCallback, useMemo } from "react";
import Link from "next/link";
import { Card } from "@/components/common";
import { useSocket } from "@/lib/socket";
import apiClient from "@/lib/api/client";

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
}

// 统一信号项
interface UnifiedSignal {
  id: string;
  source: "sniper" | "alert" | "pipeline";
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
}

// ── 信号类型标签 ──────────────────────────────────

const SNIPER_LABELS: Record<string, string> = {
  mega_sell: "巨量砸盘", mega_buy: "巨量抢筹",
  distribution_trap: "出货陷阱", accumulation_signal: "主力吸筹",
};

const PRIMARY_SNIPER_TYPES = new Set(["mega_buy", "mega_sell", "distribution_trap", "accumulation_signal"]);

// ── Props ──────────────────────────────────────

interface UnifiedSignalFeedProps {
  positionStockCodes?: string[];   // 持仓股票代码列表（用于优先排序）
  maxItems?: number;
}

export function UnifiedSignalFeed({ positionStockCodes = [], maxItems = 20 }: UnifiedSignalFeedProps) {
  const { socket } = useSocket();
  const [sniperSignals, setSniperSignals] = useState<SniperSignal[]>([]);
  const [vpAlerts, setVpAlerts] = useState<VolumePriceAlert[]>([]);
  const [pipelineRecords, setPipelineRecords] = useState<PipelineRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);

  const positionSet = useMemo(() => new Set(positionStockCodes), [positionStockCodes]);

  // ── 数据加载 ──────────────────────────────────

  const loadData = useCallback(async () => {
    try {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const [sigRes, vpRes, pipeRes]: any[] = await Promise.all([
        apiClient.get("/sniper/signals"),
        apiClient.get("/enhanced-heat/volume-price-alerts?source=focus"),
        apiClient.get("/sniper/signal-pipeline?limit=20"),
      ]);
      if (sigRes.success && Array.isArray(sigRes.data)) setSniperSignals(sigRes.data);
      if (vpRes.success && Array.isArray(vpRes.data)) setVpAlerts(vpRes.data);
      if (pipeRes.success && Array.isArray(pipeRes.data)) setPipelineRecords(pipeRes.data);
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

    socket.on("sniper_signal", handleSniper);
    socket.on("signal_pipeline", handlePipeline);
    return () => {
      socket.off("sniper_signal", handleSniper);
      socket.off("signal_pipeline", handlePipeline);
    };
  }, [socket]);

  // ── 转换为统一信号格式 ──────────────────────────

  const unifiedSignals = useMemo((): UnifiedSignal[] => {
    const items: UnifiedSignal[] = [];

    // 1. 狙击信号 → 只取主信号
    for (const sig of sniperSignals) {
      if (!PRIMARY_SNIPER_TYPES.has(sig.signal_type)) continue;

      const isTrap = sig.signal_type === "distribution_trap";
      const isAcc = sig.signal_type === "accumulation_signal";
      const isBuy = sig.signal_type === "mega_buy";

      let bgColor: string, textColor: string, badgeColor: string;
      if (isTrap) {
        bgColor = "bg-amber-50/80 border-amber-300/60 dark:bg-amber-950/30 dark:border-amber-800/40";
        textColor = "text-amber-700 dark:text-amber-400";
        badgeColor = "bg-amber-200/80 text-amber-800 dark:bg-amber-900/50 dark:text-amber-300";
      } else if (isAcc) {
        bgColor = "bg-cyan-50/80 border-cyan-300/60 dark:bg-cyan-950/30 dark:border-cyan-800/40";
        textColor = "text-cyan-700 dark:text-cyan-400";
        badgeColor = "bg-cyan-200/80 text-cyan-800 dark:bg-cyan-900/50 dark:text-cyan-300";
      } else if (sig.is_red) {
        bgColor = "bg-red-50/60 border-red-200/50 dark:bg-red-950/20 dark:border-red-900/30";
        textColor = "text-red-600 dark:text-red-400";
        badgeColor = "bg-red-200/70 text-red-700 dark:bg-red-900/50 dark:text-red-300";
      } else {
        bgColor = "bg-emerald-50/60 border-emerald-200/50 dark:bg-emerald-950/20 dark:border-emerald-900/30";
        textColor = "text-emerald-600 dark:text-emerald-400";
        badgeColor = "bg-emerald-200/70 text-emerald-700 dark:bg-emerald-900/50 dark:text-emerald-300";
      }

      items.push({
        id: `sniper-${sig.stock_code}-${sig.signal_type}-${sig.time}`,
        source: "sniper",
        time: sig.time,
        stock_code: sig.stock_code,
        stock_name: sig.stock_name,
        emoji: isTrap ? "⚠️" : sig.emoji,
        label: SNIPER_LABELS[sig.signal_type] || sig.signal_type,
        detail: sig.detail,
        urgency: isTrap ? 90 : sig.is_red ? 85 : isBuy ? 80 : 70,
        is_red: sig.is_red || isTrap,
        bgColor, textColor, badgeColor,
        price: sig.price,
      });
    }

    // 2. 量价预警 → 吸收/拉升/放量跌
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
        id: `alert-${alert.stock_code}-${alert.alert_type}-${alert.start_time}`,
        source: "alert",
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

    // 3. 策略追踪 → 只取已执行的
    for (const rec of pipelineRecords) {
      if (rec.final_action !== "executed") continue;
      const isBuy = rec.direction === "BUY";
      items.push({
        id: `pipe-${rec.id || rec.timestamp}`,
        source: "pipeline",
        time: rec.timestamp?.slice(11, 16) || "",
        stock_code: rec.stock_code,
        stock_name: rec.stock_name,
        emoji: isBuy ? "✅" : "🔻",
        label: `策略${isBuy ? "买入" : "卖出"}`,
        detail: rec.final_reason,
        urgency: 50,
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

    return items.slice(0, maxItems);
  }, [sniperSignals, vpAlerts, pipelineRecords, positionSet, maxItems]);

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

                  {/* 详情 + 操作按钮 */}
                  <div className="flex items-center justify-between mt-1 gap-2">
                    <span className={`text-[10px] ${sig.textColor} opacity-75 truncate flex-1`}>
                      {sig.detail}
                    </span>
                    <div className="flex items-center gap-1 shrink-0">
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
                      <Link
                        href={`/trading?stock=${sig.stock_code}`}
                        onClick={(e) => { e.stopPropagation(); }}
                        className="text-[9px] px-1.5 py-0.5 rounded bg-primary/10 text-primary hover:bg-primary/20 transition-colors font-medium"
                      >
                        📈下单
                      </Link>
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
