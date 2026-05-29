// 盘后优选 — 首页 Dashboard 卡片（实时跟踪决策面板）

"use client";

import { useState, useEffect, useCallback } from "react";
import { Card } from "@/components/common";
import apiClient from "@/lib/api/client";

interface SniperSignalItem {
  type: string; // mega_buy | mega_sell
  time: string;
  detail: string;
}

interface OvernightItem {
  stock_code: string;
  stock_name: string;
  total_score: number;
  category: string;
  verdict: string;
  reasons: string[];
  screen_change_rate: number;
  live_price: number;
  live_change_rate: number;
  capital_signal: string;
  capital_score: number;
  net_inflow_ratio: number;
  big_order_ratio: number;
  volume_ratio: number;
  sniper_signals: SniperSignalItem[];
}

export function OvernightScreenCard() {
  const [items, setItems] = useState<OvernightItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);
  const [expandedIdx, setExpandedIdx] = useState<number | null>(null);

  const loadData = useCallback(async () => {
    try {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const res: any = await apiClient.get("/overnight-screen/dashboard");
      if (res.success && res.data?.items) {
        setItems(res.data.items);
      }
      setLastUpdate(new Date());
    } catch (e) {
      console.error("加载盘后优选失败:", e);
    } finally {
      setLoading(false);
    }
  }, []);

  // 初始加载 + 3分钟轮询
  useEffect(() => {
    loadData();
    const timer = setInterval(loadData, 180000);
    return () => clearInterval(timer);
  }, [loadData]);

  // 评级徽章
  const verdictBadge = (verdict: string) => {
    const map: Record<string, { bg: string; text: string }> = {
      "强烈推荐": { bg: "bg-red-100 border-red-200", text: "text-red-700" },
      "推荐": { bg: "bg-amber-100 border-amber-200", text: "text-amber-700" },
      "可关注": { bg: "bg-blue-100 border-blue-200", text: "text-blue-700" },
      "观望": { bg: "bg-gray-100 border-gray-200", text: "text-gray-500" },
    };
    const s = map[verdict] || map["观望"];
    return (
      <span className={`text-[9px] px-1.5 py-0.5 rounded border font-bold ${s.bg} ${s.text}`}>
        {verdict}
      </span>
    );
  };

  // 类别标签
  const categoryTag = (cat: string) => {
    const colors: Record<string, string> = {
      "趋势追涨": "bg-purple-100/80 text-purple-700",
      "蓄势突破": "bg-teal-100/80 text-teal-700",
      "强势延续": "bg-orange-100/80 text-orange-700",
    };
    return (
      <span className={`text-[9px] px-1 py-px rounded font-medium ${colors[cat] || "bg-gray-100 text-gray-600"}`}>
        {cat}
      </span>
    );
  };

  // 资金信号颜色
  const capitalColor = (signal: string) => {
    if (signal === "偏多") return "text-red-600";
    if (signal === "偏空") return "text-green-600";
    return "text-gray-500";
  };

  // 涨跌颜色
  const chgColor = (v: number) => (v > 0 ? "text-red-600" : v < 0 ? "text-green-600" : "text-gray-500");
  const fmtChg = (v: number) => `${v >= 0 ? "+" : ""}${(v || 0).toFixed(2)}%`;

  return (
    <Card>
      <div className="p-4 md:p-5">
        {/* 标题栏 */}
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-base font-semibold text-gray-900 flex items-center gap-1.5">
            <span className="text-base">🌙</span>
            盘后优选
            {items.length > 0 && (
              <span className="text-[10px] font-normal text-gray-400 ml-1">
                {items.length}只
              </span>
            )}
          </h3>
          <div className="flex items-center gap-2">
            <span className="text-[10px] text-gray-400">
              {lastUpdate ? `${lastUpdate.toLocaleTimeString("zh-CN")} 更新` : ""}
            </span>
            <button
              onClick={() => { setLoading(true); loadData(); }}
              className="p-1 rounded hover:bg-gray-100 transition-colors"
              title="刷新"
            >
              <svg className="w-3.5 h-3.5 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
              </svg>
            </button>
          </div>
        </div>

        {loading ? (
          <div className="text-center py-6 text-gray-400 text-sm">加载中...</div>
        ) : items.length === 0 ? (
          <div className="text-center py-6 text-gray-400 text-sm">
            暂无优选数据 — 收盘后自动生成
          </div>
        ) : (
          <div className="space-y-1.5">
            {items.map((item, idx) => (
              <div
                key={item.stock_code}
                className={`rounded-lg border px-3 py-2 transition-all cursor-pointer hover:shadow-sm ${
                  item.verdict === "强烈推荐"
                    ? "bg-gradient-to-r from-red-50/60 to-amber-50/40 border-red-200/60"
                    : item.verdict === "推荐"
                    ? "bg-gradient-to-r from-amber-50/50 to-yellow-50/30 border-amber-200/50"
                    : "bg-gray-50/50 border-gray-200/60"
                }`}
                onClick={() => setExpandedIdx(expandedIdx === idx ? null : idx)}
              >
                {/* 第一行：排名 + 股名 + 类别 + 评级 + 评分 */}
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-1.5 min-w-0">
                    <span className="text-[10px] font-bold text-gray-400 w-4 shrink-0">
                      {idx + 1}
                    </span>
                    <span className="text-[12px] font-bold text-gray-900 truncate max-w-[80px]">
                      {item.stock_name}
                    </span>
                    {categoryTag(item.category)}
                    {verdictBadge(item.verdict)}
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-indigo-100 text-indigo-700 font-bold tabular-nums">
                      {item.total_score.toFixed(0)}分
                    </span>
                  </div>
                </div>

                {/* 第二行：实时数据指标 */}
                <div className="flex items-center gap-3 mt-1.5 flex-wrap">
                  {/* 巨量抢筹/砸盘信号 */}
                  {item.sniper_signals && item.sniper_signals.length > 0 && item.sniper_signals.map((sig, si) => {
                    const isBuy = sig.type === 'mega_buy';
                    return (
                      <span
                        key={si}
                        className={`text-[9px] px-1.5 py-0.5 rounded-full font-bold border ${
                          isBuy
                            ? 'bg-emerald-100 border-emerald-300 text-emerald-700'
                            : 'bg-red-100 border-red-300 text-red-700'
                        }`}
                        title={sig.detail}
                      >
                        {isBuy ? '🟢 巨量抢筹' : '🔴 巨量砸盘'} {sig.time}
                      </span>
                    );
                  })}
                  {/* 实时涨跌 */}
                  <div className="flex items-center gap-0.5">
                    <span className="text-[9px] text-gray-400">涨跌</span>
                    <span className={`text-[11px] font-bold tabular-nums ${chgColor(item.live_change_rate)}`}>
                      {fmtChg(item.live_change_rate)}
                    </span>
                  </div>
                  {/* 资金信号 */}
                  <div className="flex items-center gap-0.5">
                    <span className="text-[9px] text-gray-400">资金</span>
                    <span className={`text-[11px] font-bold ${capitalColor(item.capital_signal)}`}>
                      {item.capital_signal}
                    </span>
                    <span className="text-[9px] text-gray-400">
                      ({item.capital_score})
                    </span>
                  </div>
                  {/* 大单比 */}
                  {item.big_order_ratio > 0 && (
                    <div className="flex items-center gap-0.5">
                      <span className="text-[9px] text-gray-400">大单</span>
                      <span className={`text-[11px] font-bold tabular-nums ${
                        item.big_order_ratio >= 1.5 ? "text-red-600" : item.big_order_ratio < 0.7 ? "text-green-600" : "text-gray-600"
                      }`}>
                        {item.big_order_ratio.toFixed(1)}
                      </span>
                    </div>
                  )}
                  {/* 量比 */}
                  {item.volume_ratio > 0 && (
                    <div className="flex items-center gap-0.5">
                      <span className="text-[9px] text-gray-400">量比</span>
                      <span className={`text-[11px] font-bold tabular-nums ${
                        item.volume_ratio >= 2 ? "text-red-600" : "text-gray-600"
                      }`}>
                        {item.volume_ratio.toFixed(1)}
                      </span>
                    </div>
                  )}
                  {/* 价格 */}
                  {item.live_price > 0 && (
                    <div className="flex items-center gap-0.5">
                      <span className="text-[9px] text-gray-400">价</span>
                      <span className="text-[11px] font-medium tabular-nums text-gray-700">
                        {item.live_price.toFixed(3)}
                      </span>
                    </div>
                  )}
                </div>

                {/* 展开：推荐理由 */}
                {expandedIdx === idx && item.reasons.length > 0 && (
                  <div className="mt-2 pt-1.5 border-t border-gray-200/60">
                    <div className="flex flex-wrap gap-1">
                      {item.reasons.map((r, ri) => (
                        <span key={ri} className="text-[9px] px-1.5 py-0.5 rounded bg-blue-50 text-blue-600 border border-blue-100/60">
                          {r}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </Card>
  );
}
