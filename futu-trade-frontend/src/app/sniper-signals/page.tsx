// 盘中狙击 — 全部信号历史页面
// 支持：全天信号浏览、关键词搜索、类型筛选、WebSocket 实时推送

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
}

const TYPE_LABELS: Record<string, string> = {
  mega_sell: "巨量砸盘",
  mega_buy: "巨量抢筹",
  reversal_bear: "资金转负",
  reversal_bull: "资金转正",
  accel_in: "资金加速",
  sustained_out: "持续流出",
  distribution_trap: "出货陷阱",
};

const ALL_TYPES = Object.keys(TYPE_LABELS);

export default function SniperSignalsPage() {
  const { socket } = useSocket();
  const [signals, setSignals] = useState<SniperSignal[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [activeType, setActiveType] = useState<string | null>(null);
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);

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

  // 筛选逻辑
  const filtered = useMemo(() => {
    let list = [...signals].sort((a, b) => b.time.localeCompare(a.time));
    if (activeType) {
      list = list.filter((s) => s.signal_type === activeType);
    }
    if (search.trim()) {
      const q = search.trim().toLowerCase();
      list = list.filter(
        (s) =>
          s.stock_name.toLowerCase().includes(q) ||
          s.stock_code.toLowerCase().includes(q)
      );
    }
    return list;
  }, [signals, activeType, search]);

  // 按 stock_code + time 分组，合并同一股票同一时间的多个信号
  interface GroupedSignal {
    time: string;
    stock_code: string;
    stock_name: string;
    price: number;
    is_red: boolean;
    emoji: string;
    signals: { signal_type: string; detail: string; is_red: boolean; emoji: string }[];
  }

  const grouped = useMemo((): GroupedSignal[] => {
    const map = new Map<string, GroupedSignal>();
    for (const sig of filtered) {
      const key = `${sig.stock_code}:${sig.time}`;
      if (!map.has(key)) {
        map.set(key, {
          time: sig.time,
          stock_code: sig.stock_code,
          stock_name: sig.stock_name,
          price: sig.price,
          is_red: sig.is_red,
          emoji: sig.emoji,
          signals: [],
        });
      }
      map.get(key)!.signals.push({
        signal_type: sig.signal_type,
        detail: sig.detail,
        is_red: sig.is_red,
        emoji: sig.emoji,
      });
    }
    return Array.from(map.values());
  }, [filtered]);

  // 统计
  const stats = useMemo(() => {
    const bullCount = signals.filter((s) => !s.is_red).length;
    const bearCount = signals.filter((s) => s.is_red).length;
    const stockSet = new Set(signals.map((s) => s.stock_code));
    // 最活跃个股
    const freq: Record<string, { name: string; count: number }> = {};
    signals.forEach((s) => {
      if (!freq[s.stock_code]) freq[s.stock_code] = { name: s.stock_name, count: 0 };
      freq[s.stock_code].count++;
    });
    const topStock = Object.values(freq).sort((a, b) => b.count - a.count)[0];
    return { total: signals.length, bullCount, bearCount, stockCount: stockSet.size, topStock };
  }, [signals]);

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
            <span>🎯</span> 盘中狙击 — 全部信号
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
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3 mb-4 md:mb-6">
        <Card>
          <div className="p-3 md:p-4 text-center">
            <div className="text-2xl font-bold text-foreground">{stats.total}</div>
            <div className="text-[11px] text-muted-foreground mt-1">今日信号总数</div>
          </div>
        </Card>
        <Card>
          <div className="p-3 md:p-4 text-center">
            <div className="text-2xl font-bold text-emerald-600">{stats.bullCount}</div>
            <div className="text-[11px] text-muted-foreground mt-1">🟢 多头信号</div>
          </div>
        </Card>
        <Card>
          <div className="p-3 md:p-4 text-center">
            <div className="text-2xl font-bold text-red-600">{stats.bearCount}</div>
            <div className="text-[11px] text-muted-foreground mt-1">🔴 空头信号</div>
          </div>
        </Card>
        <Card>
          <div className="p-3 md:p-4 text-center">
            <div className="text-2xl font-bold text-blue-600">{stats.stockCount}</div>
            <div className="text-[11px] text-muted-foreground mt-1">涉及个股</div>
          </div>
        </Card>
        <Card>
          <div className="p-3 md:p-4 text-center col-span-2 md:col-span-1">
            <div className="text-lg font-bold text-foreground truncate">
              {stats.topStock ? stats.topStock.name : "—"}
            </div>
            <div className="text-[11px] text-muted-foreground mt-1">
              最活跃 {stats.topStock ? `(${stats.topStock.count}次)` : ""}
            </div>
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
          {ALL_TYPES.map((type) => {
            const isRed = ["mega_sell", "reversal_bear", "sustained_out"].includes(type);
            const isActive = activeType === type;
            return (
              <button
                key={type}
                onClick={() => setActiveType(isActive ? null : type)}
                className={`px-2.5 py-1 text-[11px] font-medium rounded-md transition-colors ${
                  isActive
                    ? isRed
                      ? "bg-red-500 text-white shadow-sm"
                      : "bg-emerald-500 text-white shadow-sm"
                    : isRed
                      ? "bg-red-50 text-red-600 hover:bg-red-100 dark:bg-red-950/30 dark:text-red-400 dark:hover:bg-red-950/50"
                      : "bg-emerald-50 text-emerald-600 hover:bg-emerald-100 dark:bg-emerald-950/30 dark:text-emerald-400 dark:hover:bg-emerald-950/50"
                }`}
              >
                {TYPE_LABELS[type]}
              </button>
            );
          })}
        </div>
      </div>

      {/* 信号列表 */}
      {loading ? (
        <div className="text-center py-16 text-muted-foreground">加载中...</div>
      ) : filtered.length === 0 ? (
        <Card>
          <div className="text-center py-16 text-muted-foreground text-sm">
            {signals.length === 0 ? "暂无信号 — 引擎每3分钟扫描一次" : "没有匹配的信号"}
          </div>
        </Card>
      ) : (
        <Card>
          <div className="p-3 md:p-4">
            <div className="text-[11px] text-muted-foreground mb-3">
              共 {filtered.length} 条信号，{grouped.length} 只个股{activeType ? ` · ${TYPE_LABELS[activeType]}` : ""}{search ? ` · "${search}"` : ""}
            </div>
            <div className="space-y-1.5">
              {grouped.map((g) => {
                const hasRed = g.signals.some((s) => s.is_red);
                const hasGreen = g.signals.some((s) => !s.is_red);
                const bgColor = hasRed && !hasGreen
                  ? "bg-red-50/60 border-red-200/50 dark:bg-red-950/20 dark:border-red-900/30"
                  : !hasRed && hasGreen
                    ? "bg-emerald-50/60 border-emerald-200/50 dark:bg-emerald-950/20 dark:border-emerald-900/30"
                    : "bg-amber-50/40 border-amber-200/50 dark:bg-amber-950/20 dark:border-amber-900/30";
                const nameColor = hasRed && !hasGreen
                  ? "text-red-600 dark:text-red-400"
                  : "text-emerald-600 dark:text-emerald-400";

                return (
                  <Link
                    key={`${g.stock_code}-${g.time}`}
                    href={`/stock-detail?code=${g.stock_code}`}
                    className={`block px-3 py-2 rounded-lg border ${bgColor} hover:shadow-sm transition-all group`}
                  >
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-1.5 min-w-0 flex-wrap">
                        <span className="text-[10px] font-mono tabular-nums text-muted-foreground shrink-0">
                          {g.time}
                        </span>
                        <span className="text-xs">{g.emoji}</span>
                        <span className={`font-bold text-sm ${nameColor} truncate group-hover:underline`}>
                          {g.stock_name}
                        </span>
                        <span className="text-[10px] text-muted-foreground shrink-0">
                          {g.stock_code}
                        </span>
                        {g.signals.map((s, i) => {
                          const bc = s.is_red
                            ? "bg-red-200/70 text-red-700 dark:bg-red-900/50 dark:text-red-300"
                            : "bg-emerald-200/70 text-emerald-700 dark:bg-emerald-900/50 dark:text-emerald-300";
                          return (
                            <span key={i} className={`text-[9px] px-1.5 py-0.5 rounded font-medium shrink-0 ${bc}`}>
                              {TYPE_LABELS[s.signal_type] || s.signal_type}
                            </span>
                          );
                        })}
                      </div>
                      <div className="flex items-center gap-2 shrink-0 ml-2">
                        <span className="text-xs font-bold tabular-nums text-foreground/70">
                          {g.price.toFixed(3)}
                        </span>
                        <svg className="w-3.5 h-3.5 text-muted-foreground opacity-0 group-hover:opacity-100 transition-opacity" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                        </svg>
                      </div>
                    </div>
                    <div className="text-[11px] text-muted-foreground/70 mt-0.5 space-x-2 truncate">
                      {g.signals.map((s, i) => (
                        <span key={i} className={s.is_red ? "text-red-500/70 dark:text-red-400/70" : "text-emerald-500/70 dark:text-emerald-400/70"}>
                          {s.detail}
                        </span>
                      ))}
                    </div>
                  </Link>
                );
              })}
            </div>
          </div>
        </Card>
      )}
    </div>
  );
}
