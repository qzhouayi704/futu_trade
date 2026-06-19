// 日内资金动能扫描面板
// 从后端 /flow-momentum-scan 获取所有股票的资金流动能，按信号排序展示

"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import apiClient from "@/lib/api/client";

interface FlowScanItem {
  stock_code: string;
  stock_name: string;
  price: number;
  data_points: number;
  momentum_label: string;
  momentum_change: number;
  signal: "bullish" | "bearish" | "warning" | "neutral";
  buy_sell_ratio: number;
  cum_net: number;
  recent_net: number;
  first_half_net: number;
  second_half_net: number;
}

const SIGNAL_CONFIG: Record<string, { bg: string; text: string; dot: string; border: string }> = {
  bullish:  { bg: "bg-red-50",      text: "text-red-700",      dot: "bg-red-500",      border: "border-red-200" },
  warning:  { bg: "bg-amber-50",    text: "text-amber-700",    dot: "bg-amber-500",    border: "border-amber-200" },
  bearish:  { bg: "bg-emerald-50",  text: "text-emerald-700",  dot: "bg-emerald-500",  border: "border-emerald-200" },
  neutral:  { bg: "bg-muted",     text: "text-muted-foreground",     dot: "bg-gray-400",     border: "border-border" },
};

const fmtAmt = (v: number) => {
  const abs = Math.abs(v);
  if (abs >= 10000) return `${(v / 10000).toFixed(1)}亿`;
  return `${v.toFixed(0)}万`;
};

interface FlowMomentumScanPanelProps {
  onSelectStock?: (code: string) => void;
}

export default function FlowMomentumScanPanel({ onSelectStock }: FlowMomentumScanPanelProps) {
  const [items, setItems] = useState<FlowScanItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState("");
  const [filter, setFilter] = useState<"all" | "bullish" | "warning" | "bearish">("all");
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchData = useCallback(async () => {
    try {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const res: any = await apiClient.get("/enhanced-heat/flow-momentum-scan");
      if (res.success) {
        setItems(res.data || []);
        setMessage(res.message || "");
      }
    } catch {
      /* ignore */
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    timerRef.current = setInterval(fetchData, 60_000); // 60秒刷新
    return () => { if (timerRef.current) clearInterval(timerRef.current); };
  }, [fetchData]);

  const filtered = filter === "all" ? items : items.filter((i) => i.signal === filter);

  const bullishCount = items.filter((i) => i.signal === "bullish").length;
  const warningCount = items.filter((i) => i.signal === "warning").length;
  const bearishCount = items.filter((i) => i.signal === "bearish").length;

  return (
    <div className="p-4 space-y-4">
      {/* 标题 + 统计 */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <h2 className="text-lg font-bold text-foreground">日内资金动能扫描</h2>
          <span className="text-xs text-muted-foreground">{message}</span>
        </div>
        <button
          onClick={() => { setLoading(true); fetchData(); }}
          className="text-xs text-blue-500 hover:text-blue-700 transition-colors"
        >
          🔄 刷新
        </button>
      </div>

      {/* 过滤按钮 */}
      <div className="flex gap-2 flex-wrap">
        {[
          { id: "all" as const, label: `全部 (${items.length})`, color: "bg-muted text-foreground" },
          { id: "bullish" as const, label: `🔴 流入 (${bullishCount})`, color: "bg-red-100 text-red-700" },
          { id: "warning" as const, label: `🟡 注意 (${warningCount})`, color: "bg-amber-100 text-amber-700" },
          { id: "bearish" as const, label: `🟢 流出 (${bearishCount})`, color: "bg-emerald-100 text-emerald-700" },
        ].map((btn) => (
          <button
            key={btn.id}
            onClick={() => setFilter(btn.id)}
            className={`px-3 py-1.5 rounded-full text-xs font-medium transition-all ${
              filter === btn.id
                ? `${btn.color} ring-2 ring-offset-1 ring-current`
                : "bg-muted text-muted-foreground hover:bg-muted"
            }`}
          >
            {btn.label}
          </button>
        ))}
      </div>

      {/* 列表 */}
      {loading ? (
        <div className="flex items-center justify-center py-16">
          <div className="w-8 h-8 border-3 border-blue-500 border-t-transparent rounded-full animate-spin" />
          <span className="ml-3 text-sm text-muted-foreground">扫描中...</span>
        </div>
      ) : filtered.length === 0 ? (
        <div className="text-center py-16 text-muted-foreground text-sm">暂无匹配的股票</div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
          {filtered.map((item) => {
            const cfg = SIGNAL_CONFIG[item.signal] || SIGNAL_CONFIG.neutral;
            const mcSign = item.momentum_change >= 0 ? "+" : "";
            return (
              <div
                key={item.stock_code}
                onClick={() => onSelectStock?.(item.stock_code)}
                className={`p-3 rounded-xl border ${cfg.border} ${cfg.bg} cursor-pointer 
                  hover:shadow-md hover:scale-[1.02] transition-all duration-200`}
              >
                {/* 顶行：股票代码 + 信号标签 */}
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <div className={`w-2 h-2 rounded-full ${cfg.dot}`} />
                    <span className="text-sm font-bold text-foreground">
                      {item.stock_name || item.stock_code}
                    </span>
                    <span className="text-[10px] text-muted-foreground">{item.stock_code}</span>
                    {item.price > 0 && (
                      <span className="text-xs text-muted-foreground">{item.price.toFixed(2)}</span>
                    )}
                  </div>
                  <span className={`text-xs font-bold px-2 py-0.5 rounded-full ${cfg.bg} ${cfg.text} border ${cfg.border}`}>
                    {item.momentum_label}
                  </span>
                </div>

                {/* 指标行 */}
                <div className="flex items-center gap-3 text-[11px]">
                  <span className={item.cum_net >= 0 ? "text-red-600" : "text-emerald-600"}>
                    累计 {item.cum_net >= 0 ? "+" : ""}{fmtAmt(item.cum_net)}
                  </span>
                  <span className="text-gray-300">|</span>
                  <span className={item.buy_sell_ratio >= 1 ? "text-red-500" : "text-emerald-500"}>
                    买卖比 {item.buy_sell_ratio.toFixed(2)}
                  </span>
                  <span className="text-gray-300">|</span>
                  <span className="text-muted-foreground">
                    动能 {mcSign}{item.momentum_change}%
                  </span>
                </div>

                {/* 近5分钟 */}
                <div className="mt-1.5 flex items-center gap-2 text-[10px] text-muted-foreground">
                  <span>近5分</span>
                  <span className={item.recent_net >= 0 ? "text-red-500 font-medium" : "text-emerald-500 font-medium"}>
                    {item.recent_net >= 0 ? "+" : ""}{fmtAmt(item.recent_net)}
                  </span>
                  <span className="ml-auto">{item.data_points} 分钟数据</span>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
