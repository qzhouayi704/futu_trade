// 盘中狙击 — 全部信号历史页面
// 设计理念：主信号(mega_buy/mega_sell/distribution_trap)为核心卡片，确认信号折叠展示

"use client";

import { useState, useEffect, useCallback, useMemo } from "react";
import Link from "next/link";
import { Card } from "@/components/common";
import { useSocket } from "@/lib/socket";
import apiClient from "@/lib/api/client";

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
  strength?: number;
  strength_label?: string;
}

const TYPE_LABELS: Record<string, string> = {
  mega_sell: "巨量砸盘",
  mega_buy: "巨量抢筹",
  reversal_bear: "资金转负",
  reversal_bull: "资金转正",
  accel_in: "资金加速",
  sustained_out: "持续流出",
  distribution_trap: "出货陷阱",
  accumulation_signal: "主力吸筹",
};

// 主信号 = 核心决策依据
const PRIMARY_TYPES = new Set(["mega_buy", "mega_sell", "distribution_trap", "accumulation_signal"]);
// 确认信号 = 辅助佐证
const CONFIRM_TYPES = new Set(["accel_in", "reversal_bull", "sustained_out", "reversal_bear"]);

// 筛选标签：只展示主信号类型
const FILTER_TYPES = ["mega_buy", "mega_sell", "distribution_trap", "accumulation_signal"];

// 时间字符串转分钟数
function timeToMinutes(t: string): number {
  const [h, m] = t.split(":").map(Number);
  return h * 60 + m;
}

// 聚合后的卡片数据
interface SignalCard {
  primary: SniperSignal;                 // 主信号
  confirms: SniperSignal[];              // 时间窗口内的确认信号
  confirmCount: number;                  // 确认信号数量（共振强度）
}

export default function SniperSignalsPage() {
  const { socket } = useSocket();
  const [signals, setSignals] = useState<SniperSignal[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [activeType, setActiveType] = useState<string | null>(null);
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);
  const [expandedCards, setExpandedCards] = useState<Set<string>>(new Set());

  // 加载全部信号
  const loadSignals = useCallback(async () => {
    try {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const res: any = await apiClient.get("/sniper/signals");
      if (res.success && Array.isArray(res.data)) {
        setSignals(res.data);
        setLastUpdate(new Date());
      }
    } catch (e) {
      console.error("加载信号失败:", e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadSignals();
    const timer = setInterval(loadSignals, 180000);
    return () => clearInterval(timer);
  }, [loadSignals]);

  // WebSocket 实时信号
  useEffect(() => {
    if (!socket) return;
    const handler = (data: SniperSignal) => {
      setSignals((prev) => {
        const updated = [data, ...prev];
        const seen = new Set<string>();
        return updated.filter((s) => {
          const key = `${s.stock_code}:${s.signal_type}:${s.time}`;
          if (seen.has(key)) return false;
          seen.add(key);
          return true;
        });
      });
      setLastUpdate(new Date());
    };
    socket.on("sniper_signal", handler);
    return () => { socket.off("sniper_signal", handler); };
  }, [socket]);

  // 构建分层卡片：主信号为核心，15分钟内的确认信号附属
  const cards = useMemo((): SignalCard[] => {
    // 按股票分组全部信号
    const byStock = new Map<string, SniperSignal[]>();
    for (const sig of signals) {
      const arr = byStock.get(sig.stock_code) || [];
      arr.push(sig);
      byStock.set(sig.stock_code, arr);
    }

    const result: SignalCard[] = [];

    for (const [, stockSignals] of byStock) {
      const primaries = stockSignals.filter((s) => PRIMARY_TYPES.has(s.signal_type));
      const confirms = stockSignals.filter((s) => CONFIRM_TYPES.has(s.signal_type));

      // 每个主信号配对15分钟窗口内的确认信号
      for (const p of primaries) {
        const pMin = timeToMinutes(p.time);
        const nearby = confirms.filter((c) => {
          const cMin = timeToMinutes(c.time);
          return Math.abs(cMin - pMin) <= 15;
        });
        result.push({
          primary: p,
          confirms: nearby.sort((a, b) => a.time.localeCompare(b.time)),
          confirmCount: nearby.length,
        });
      }
    }

    // 按时间倒序
    result.sort((a, b) => b.primary.time.localeCompare(a.primary.time));
    return result;
  }, [signals]);

  // 筛选
  const filtered = useMemo(() => {
    let list = cards;
    if (activeType) {
      list = list.filter((c) => c.primary.signal_type === activeType);
    }
    if (search.trim()) {
      const q = search.trim().toLowerCase();
      list = list.filter(
        (c) =>
          c.primary.stock_name.toLowerCase().includes(q) ||
          c.primary.stock_code.toLowerCase().includes(q)
      );
    }
    return list;
  }, [cards, activeType, search]);

  // 统计
  const stats = useMemo(() => {
    const buyCount = cards.filter((c) => c.primary.signal_type === "mega_buy").length;
    const sellCount = cards.filter((c) => c.primary.signal_type === "mega_sell").length;
    const trapCount = cards.filter((c) => c.primary.signal_type === "distribution_trap").length;
    const accCount = cards.filter((c) => c.primary.signal_type === "accumulation_signal").length;
    const stockSet = new Set(cards.map((c) => c.primary.stock_code));
    const withConfirm = cards.filter((c) => c.confirmCount > 0).length;
    return { total: cards.length, buyCount, sellCount, trapCount, accCount, stockCount: stockSet.size, withConfirm };
  }, [cards]);

  const toggleExpand = (key: string) => {
    setExpandedCards((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key); else next.add(key);
      return next;
    });
  };

  return (
    <div className="container mx-auto px-3 md:px-4 py-4 md:py-6 max-w-7xl">
      {/* 页面标题 */}
      <div className="flex items-center justify-between mb-4 md:mb-6">
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
            <span>🎯</span> 盘中狙击 — 信号中心
          </h1>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-[10px] text-muted-foreground">
            {lastUpdate ? `${lastUpdate.toLocaleTimeString("zh-CN")} 更新` : ""}
          </span>
          <button
            onClick={() => { setLoading(true); loadSignals(); }}
            className="px-3 py-1.5 text-sm text-primary hover:bg-primary/5 rounded-lg transition-colors"
          >
            🔄 刷新
          </button>
        </div>
      </div>

      {/* 统计面板 */}
      <div className="grid grid-cols-3 md:grid-cols-6 gap-3 mb-4 md:mb-6">
        <Card>
          <div className="p-3 text-center">
            <div className="text-2xl font-bold text-foreground">{stats.total}</div>
            <div className="text-[11px] text-muted-foreground mt-1">主信号总数</div>
          </div>
        </Card>
        <Card>
          <div className="p-3 text-center">
            <div className="text-2xl font-bold text-emerald-600">{stats.buyCount}</div>
            <div className="text-[11px] text-muted-foreground mt-1">🟢 巨量抢筹</div>
          </div>
        </Card>
        <Card>
          <div className="p-3 text-center">
            <div className="text-2xl font-bold text-red-600">{stats.sellCount}</div>
            <div className="text-[11px] text-muted-foreground mt-1">🔴 巨量砸盘</div>
          </div>
        </Card>
        <Card>
          <div className="p-3 text-center">
            <div className="text-2xl font-bold text-amber-600">{stats.trapCount}</div>
            <div className="text-[11px] text-muted-foreground mt-1">⚠️ 出货陷阱</div>
          </div>
        </Card>
        <Card>
          <div className="p-3 text-center">
            <div className="text-2xl font-bold text-cyan-600">{stats.accCount}</div>
            <div className="text-[11px] text-muted-foreground mt-1">🟢 主力吸筹</div>
          </div>
        </Card>
        <Card>
          <div className="p-3 text-center">
            <div className="text-2xl font-bold text-blue-600">{stats.stockCount}</div>
            <div className="text-[11px] text-muted-foreground mt-1">涉及个股</div>
          </div>
        </Card>
        <Card>
          <div className="p-3 text-center">
            <div className="text-2xl font-bold text-purple-600">{stats.withConfirm}</div>
            <div className="text-[11px] text-muted-foreground mt-1">🔗 有确认信号</div>
          </div>
        </Card>
      </div>

      {/* 搜索 + 类型筛选 */}
      <div className="flex flex-col md:flex-row items-start md:items-center gap-3 mb-4">
        <div className="relative w-full md:w-64">
          <svg className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="搜索股票代码或名称..."
            className="w-full pl-9 pr-3 py-2 text-sm rounded-lg border border-border bg-background text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary transition-colors"
          />
        </div>
        <div className="flex flex-wrap gap-1.5">
          <button
            onClick={() => setActiveType(null)}
            className={`px-2.5 py-1 text-[11px] font-medium rounded-md transition-colors ${
              !activeType
                ? "bg-primary text-primary-foreground shadow-sm"
                : "bg-muted text-muted-foreground hover:bg-muted/80"
            }`}
          >
            全部
          </button>
          {FILTER_TYPES.map((type) => {
            const isActive = activeType === type;
            const colorMap: Record<string, { active: string; inactive: string }> = {
              mega_buy: {
                active: "bg-emerald-500 text-white shadow-sm",
                inactive: "bg-emerald-50 text-emerald-600 hover:bg-emerald-100 dark:bg-emerald-950/30 dark:text-emerald-400",
              },
              mega_sell: {
                active: "bg-red-500 text-white shadow-sm",
                inactive: "bg-red-50 text-red-600 hover:bg-red-100 dark:bg-red-950/30 dark:text-red-400",
              },
              distribution_trap: {
                active: "bg-amber-500 text-white shadow-sm",
                inactive: "bg-amber-50 text-amber-600 hover:bg-amber-100 dark:bg-amber-950/30 dark:text-amber-400",
              },
              accumulation_signal: {
                active: "bg-cyan-500 text-white shadow-sm",
                inactive: "bg-cyan-50 text-cyan-600 hover:bg-cyan-100 dark:bg-cyan-950/30 dark:text-cyan-400",
              },
            };
            const colors = colorMap[type] || colorMap.mega_sell;
            return (
              <button
                key={type}
                onClick={() => setActiveType(isActive ? null : type)}
                className={`px-2.5 py-1 text-[11px] font-medium rounded-md transition-colors ${
                  isActive ? colors.active : colors.inactive
                }`}
              >
                {TYPE_LABELS[type]}
              </button>
            );
          })}
        </div>
      </div>

      {/* 信号卡片列表 */}
      {loading ? (
        <div className="text-center py-16 text-muted-foreground">加载中...</div>
      ) : filtered.length === 0 ? (
        <Card>
          <div className="text-center py-16 text-muted-foreground text-sm">
            {signals.length === 0 ? "暂无信号 — 引擎每3分钟扫描一次" : "没有匹配的信号"}
          </div>
        </Card>
      ) : (
        <div className="space-y-2">
          {filtered.map((card) => {
            const p = card.primary;
            const cardKey = `${p.stock_code}:${p.signal_type}:${p.time}`;
            const isExpanded = expandedCards.has(cardKey);

            // 卡片颜色方案
            const isTrap = p.signal_type === "distribution_trap";
            const isBuy = p.signal_type === "mega_buy";
            const isAcc = p.signal_type === "accumulation_signal";

            const bgColor = isTrap
              ? "bg-amber-50/80 border-amber-300/60 dark:bg-amber-950/30 dark:border-amber-800/40"
              : isAcc
                ? "bg-cyan-50/80 border-cyan-300/60 dark:bg-cyan-950/30 dark:border-cyan-800/40"
                : p.is_red
                  ? "bg-red-50/60 border-red-200/50 dark:bg-red-950/20 dark:border-red-900/30"
                  : "bg-emerald-50/60 border-emerald-200/50 dark:bg-emerald-950/20 dark:border-emerald-900/30";

            const nameColor = isTrap
              ? "text-amber-700 dark:text-amber-400"
              : isAcc
                ? "text-cyan-700 dark:text-cyan-400"
                : p.is_red
                  ? "text-red-600 dark:text-red-400"
                  : "text-emerald-600 dark:text-emerald-400";

            const badgeColor = isTrap
              ? "bg-amber-200/80 text-amber-800 dark:bg-amber-900/50 dark:text-amber-300"
              : isAcc
                ? "bg-cyan-200/80 text-cyan-800 dark:bg-cyan-900/50 dark:text-cyan-300"
                : p.is_red
                  ? "bg-red-200/70 text-red-700 dark:bg-red-900/50 dark:text-red-300"
                  : "bg-emerald-200/70 text-emerald-700 dark:bg-emerald-900/50 dark:text-emerald-300";

            const emoji = isTrap ? "⚠️" : p.emoji;

            return (
              <Card key={cardKey}>
                <div className={`rounded-lg border ${bgColor} overflow-hidden`}>
                  {/* 主信号行 */}
                  <Link
                    href={`/stock-detail?code=${p.stock_code}`}
                    className="block px-3 py-2.5 hover:shadow-sm transition-all group"
                  >
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-1.5 min-w-0 flex-wrap">
                        <span className="text-[10px] font-mono tabular-nums text-muted-foreground shrink-0">
                          {p.time}
                        </span>
                        <span className="text-xs">{emoji}</span>
                        <span className={`font-bold text-sm ${nameColor} truncate group-hover:underline`}>
                          {p.stock_name}
                        </span>
                        <span className="text-[10px] text-muted-foreground shrink-0">
                          {p.stock_code}
                        </span>
                        <span className={`text-[9px] px-1.5 py-0.5 rounded font-bold shrink-0 ${badgeColor}`}>
                          {TYPE_LABELS[p.signal_type] || p.signal_type}
                        </span>
                        {/* 共振强度标记 */}
                        {card.confirmCount > 0 && isBuy && (
                          <span className="text-[9px] px-1.5 py-0.5 rounded font-bold bg-purple-200/70 text-purple-700 dark:bg-purple-900/50 dark:text-purple-300 shrink-0">
                            🔗 {card.confirmCount}个确认
                          </span>
                        )}
                        {/* 巨量抢筹强度评分 */}
                        {p.signal_type === "mega_buy" && p.strength != null && p.strength > 0 && (
                          <span className={`text-[9px] px-1.5 py-0.5 rounded font-bold tabular-nums shrink-0 ${
                            p.strength >= 81 ? "bg-amber-300/80 text-amber-900 dark:bg-amber-700/60 dark:text-amber-100" :
                            p.strength >= 61 ? "bg-orange-200/80 text-orange-800 dark:bg-orange-800/50 dark:text-orange-200" :
                            p.strength >= 31 ? "bg-sky-200/70 text-sky-800 dark:bg-sky-800/50 dark:text-sky-200" :
                            "bg-gray-200/70 text-gray-600 dark:bg-gray-700/50 dark:text-gray-300"
                          }`}>
                            {p.strength_label?.split(" ")[0]} {p.strength}
                          </span>
                        )}
                      </div>
                      <div className="flex items-center gap-2 shrink-0 ml-2">
                        <span className="text-xs font-bold tabular-nums text-foreground/70">
                          {p.price.toFixed(3)}
                        </span>
                        <svg className="w-3.5 h-3.5 text-muted-foreground opacity-0 group-hover:opacity-100 transition-opacity" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                        </svg>
                      </div>
                    </div>
                    <div className="text-[11px] text-muted-foreground/80 mt-1 line-clamp-2">
                      {p.detail}
                    </div>
                  </Link>

                  {/* 确认信号折叠区域 */}
                  {card.confirms.length > 0 && (
                    <>
                      <button
                        onClick={(e) => { e.preventDefault(); toggleExpand(cardKey); }}
                        className="w-full px-3 py-1 text-[10px] text-muted-foreground hover:bg-black/5 dark:hover:bg-white/5 transition-colors flex items-center gap-1 border-t border-inherit"
                      >
                        <svg
                          className={`w-3 h-3 transition-transform ${isExpanded ? "rotate-90" : ""}`}
                          fill="none" viewBox="0 0 24 24" stroke="currentColor"
                        >
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                        </svg>
                        {card.confirms.length} 个确认信号（点击展开）
                      </button>
                      {isExpanded && (
                        <div className="px-3 pb-2 space-y-1 border-t border-inherit">
                          {card.confirms.map((c, i) => {
                            const cBadge = c.is_red
                              ? "bg-red-100 text-red-600 dark:bg-red-900/30 dark:text-red-400"
                              : "bg-emerald-100 text-emerald-600 dark:bg-emerald-900/30 dark:text-emerald-400";
                            const cText = c.is_red
                              ? "text-red-500/80 dark:text-red-400/70"
                              : "text-emerald-500/80 dark:text-emerald-400/70";
                            return (
                              <div key={i} className="flex items-center gap-1.5 py-1 text-[11px]">
                                <span className="text-muted-foreground/60 font-mono text-[10px] w-10 shrink-0">
                                  {c.time}
                                </span>
                                <span className={`px-1.5 py-0.5 rounded text-[9px] font-medium shrink-0 ${cBadge}`}>
                                  {TYPE_LABELS[c.signal_type] || c.signal_type}
                                </span>
                                <span className={`truncate ${cText}`}>
                                  {c.detail}
                                </span>
                              </div>
                            );
                          })}
                        </div>
                      )}
                    </>
                  )}
                </div>
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}
