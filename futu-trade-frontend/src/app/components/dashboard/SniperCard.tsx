// 盘中狙击手 — 实时信号卡片 + TOP 排行榜
// WebSocket 接收实时信号 + API 轮询兜底 + 双窗口评分排行

"use client";

import { useState, useEffect, useCallback } from "react";
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
  // 提醒分层(mega_buy): 持续抢筹次数 + 已涨幅
  tier?: string;          // opportunity(机会·持续抢筹) / pulse(脉冲) / reference(追高·参考)
  mode?: string;          // trend / spike / chase
  buy_count?: number;     // 当日该股第几次 mega_buy
  intraday_gain?: number; // 信号时当日已涨幅%
  posture?: string;       // 配套出场动作
  edge?: string;          // 边际诚实标注: "unverified"=参考·无验证边际(~50%) / "holding_risk"=持仓硬风险
}

interface RankItem {
  stock_code: string;
  stock_name: string;
  score: number;
  chg: number;
  detail: {
    window: number;
    flow: number;
    momentum: number;
    signal: number;
    w_net: number;
    w_chg: number;
    combo?: number;
    multi_mega?: number;
    multi_accel?: number;
  };
}

interface Ranking {
  opportunity: RankItem[];
  risk: RankItem[];
  updated_at: string | null;
}

export function SniperCard() {
  const { socket } = useSocket();
  const [signals, setSignals] = useState<SniperSignal[]>([]);
  const [ranking, setRanking] = useState<Ranking>({ opportunity: [], risk: [], updated_at: null });
  const [loading, setLoading] = useState(true);
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);

  // 加载信号 + 排行
  const loadData = useCallback(async () => {
    try {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const [sigRes, rankRes]: any[] = await Promise.all([
        apiClient.get("/sniper/signals"),
        apiClient.get("/sniper/ranking"),
      ]);
      if (sigRes.success && Array.isArray(sigRes.data)) {
        setSignals(sigRes.data);
      }
      if (rankRes.success && rankRes.data) {
        setRanking(rankRes.data);
      }
      setLastUpdate(new Date());
    } catch (e) {
      console.error("加载狙击手数据失败:", e);
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

  const hasRanking = ranking.opportunity.length > 0 || ranking.risk.length > 0;
  // 提醒分层优先级: 机会(持续抢筹) > 其它 > 追高·参考
  const tierRank = (s: SniperSignal) =>
    s.tier === "opportunity" ? 0 : s.tier === "reference" ? 2 : 1;
  // 首页只展示巨量抢筹/砸盘/出货陷阱/吸筹信号; 机会层置顶, 其余按时间
  const recent = [...signals]
    .filter((s) => ["mega_buy", "mega_sell", "distribution_trap", "accumulation_signal"].includes(s.signal_type))
    .sort((a, b) => tierRank(a) - tierRank(b) || b.time.localeCompare(a.time))
    .slice(0, 6);

  return (
    <Card>
      <div className="p-4 md:p-5">
        {/* 标题栏 */}
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-base font-semibold text-gray-900 flex items-center gap-1.5">
            <span className="text-base">🎯</span>
            盘中狙击
          </h3>
          <span className="text-[10px] text-gray-400">
            {lastUpdate ? `${lastUpdate.toLocaleTimeString("zh-CN")} 更新` : ""}
          </span>
        </div>

        {loading ? (
          <div className="text-center py-6 text-gray-400 text-sm">扫描中...</div>
        ) : (
          <>
            {/* TOP 排行榜 */}
            {hasRanking && (
              <div className="grid grid-cols-2 gap-2 mb-3">
                {/* 机会 TOP */}
                <div className="rounded-lg bg-gradient-to-br from-emerald-50/80 to-green-50/50 border border-emerald-100/60 p-2">
                  <div className="text-[10px] font-bold text-emerald-700 mb-1.5 flex items-center gap-1">
                    <span>🟢</span> 机会 TOP 5
                  </div>
                  {ranking.opportunity.length === 0 ? (
                    <div className="text-[10px] text-gray-400 py-1">暂无</div>
                  ) : (
                    <div className="space-y-1">
                      {ranking.opportunity.map((item, idx) => (
                        <div key={item.stock_code} className="flex items-center justify-between">
                          <div className="flex items-center gap-1 min-w-0">
                            <span className="text-[10px] font-bold text-emerald-600 w-3">{idx + 1}</span>
                            <span className="text-[11px] font-medium text-gray-800 truncate">
                              {item.stock_name}
                            </span>
                          </div>
                          <div className="flex items-center gap-1.5 shrink-0">
                            <span className={`text-[10px] font-bold tabular-nums ${item.chg >= 0 ? "text-red-500" : "text-green-600"}`}>
                              {item.chg >= 0 ? "+" : ""}{item.chg}%
                            </span>
                            <span className="text-[9px] px-1 py-px rounded bg-emerald-200/60 text-emerald-700 font-medium">
                              {item.score}
                            </span>
                            {item.detail?.combo ? (
                              <span className="text-[8px] px-0.5 py-px rounded bg-amber-200/70 text-amber-800 font-bold">共振</span>
                            ) : null}
                            {item.detail?.multi_mega ? (
                              <span className="text-[8px] px-0.5 py-px rounded bg-purple-200/70 text-purple-800 font-bold">多M</span>
                            ) : null}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>

                {/* 风险 TOP */}
                <div className="rounded-lg bg-gradient-to-br from-red-50/80 to-orange-50/50 border border-red-100/60 p-2">
                  <div className="text-[10px] font-bold text-red-700 mb-1.5 flex items-center gap-1">
                    <span>🔴</span> 风险 TOP 5
                  </div>
                  {ranking.risk.length === 0 ? (
                    <div className="text-[10px] text-gray-400 py-1">暂无</div>
                  ) : (
                    <div className="space-y-1">
                      {ranking.risk.map((item, idx) => (
                        <div key={item.stock_code} className="flex items-center justify-between">
                          <div className="flex items-center gap-1 min-w-0">
                            <span className="text-[10px] font-bold text-red-600 w-3">{idx + 1}</span>
                            <span className="text-[11px] font-medium text-gray-800 truncate">
                              {item.stock_name}
                            </span>
                          </div>
                          <div className="flex items-center gap-1.5 shrink-0">
                            <span className={`text-[10px] font-bold tabular-nums ${item.chg >= 0 ? "text-red-500" : "text-green-600"}`}>
                              {item.chg >= 0 ? "+" : ""}{item.chg}%
                            </span>
                            <span className="text-[9px] px-1 py-px rounded bg-red-200/60 text-red-700 font-medium">
                              {item.score}
                            </span>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* 信号列表 */}
            {signals.length === 0 && !hasRanking ? (
              <div className="text-center py-4 text-gray-400 text-sm">
                暂无信号 — 引擎每3分钟扫描一次
              </div>
            ) : recent.length > 0 ? (
              <div className="space-y-1">
                {recent.map((sig, idx) => {
                  const bgColor = sig.is_red
                    ? "bg-red-50/60 border-red-200/50"
                    : "bg-emerald-50/60 border-emerald-200/50";
                  const textColor = sig.is_red ? "text-red-600" : "text-emerald-600";
                  const badgeColor = sig.is_red
                    ? "bg-red-200/70 text-red-700"
                    : "bg-emerald-200/70 text-emerald-700";
                  const typeLabels: Record<string, string> = {
                    mega_sell: "巨量砸盘", mega_buy: "巨量抢筹",
                    reversal_bear: "资金转负", reversal_bull: "资金转正",
                    accel_in: "资金加速", sustained_out: "持续流出",
                  };
                  return (
                    <div
                      key={`${sig.stock_code}-${sig.signal_type}-${sig.time}-${idx}`}
                      className={`px-2 py-1.5 rounded-lg border ${bgColor}`}
                    >
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-1 min-w-0">
                          <span className="text-[10px] font-mono tabular-nums text-gray-400 shrink-0">{sig.time}</span>
                          <span className={`text-xs ${sig.is_red ? "animate-pulse" : ""}`}>{sig.emoji}</span>
                          <span className={`font-bold text-xs ${textColor} truncate`}>{sig.stock_name}</span>
                          <span className={`text-[9px] px-1 py-px rounded font-medium shrink-0 ${badgeColor}`}>
                            {typeLabels[sig.signal_type] || sig.signal_type}
                          </span>
                          {sig.edge === "unverified" && (
                            <span className="text-[9px] px-1 py-px rounded font-medium shrink-0 bg-gray-200/70 text-gray-500" title="该类信号回测约50%命中、无验证边际，仅供参考">
                              参考·无验证边际
                            </span>
                          )}
                          {sig.signal_type === "mega_buy" && sig.strength != null && sig.strength > 0 && (
                            <span className={`text-[9px] px-1 py-px rounded font-bold shrink-0 tabular-nums ${
                              sig.strength >= 81 ? "bg-amber-300/80 text-amber-900" :
                              sig.strength >= 61 ? "bg-orange-200/80 text-orange-800" :
                              sig.strength >= 31 ? "bg-sky-200/70 text-sky-800" :
                              "bg-gray-200/70 text-gray-600"
                            }`}>
                              {sig.strength_label?.split(" ")[0]} {sig.strength}
                            </span>
                          )}
                          {sig.signal_type === "mega_buy" && sig.tier && (
                            <span className={`text-[9px] px-1 py-px rounded font-bold shrink-0 ${
                              sig.tier === "opportunity" ? "bg-emerald-400/90 text-white" :
                              sig.tier === "reference" ? "bg-amber-300/80 text-amber-900" :
                              "bg-sky-200/70 text-sky-800"
                            }`}>
                              {sig.tier === "opportunity" ? `持续抢筹×${sig.buy_count ?? ""}` :
                               sig.tier === "reference" ? "急涨别碰" :
                               sig.mode === "watch" ? "单次·观察" : "谨慎·快出"}
                            </span>
                          )}
                        </div>
                        <span className="text-xs font-bold tabular-nums text-gray-600 shrink-0 ml-2">
                          {sig.price.toFixed(3)}
                        </span>
                      </div>
                      <div className={`text-[10px] ${textColor} opacity-70 mt-0.5 line-clamp-2`}>{sig.detail}</div>
                      {sig.signal_type === "mega_buy" && sig.posture && (
                        <div className="text-[10px] mt-0.5 font-medium text-gray-700 flex items-center gap-1">
                          <span>📍</span>
                          <span className="truncate">{sig.posture}</span>
                          {sig.intraday_gain != null && (
                            <span className="text-gray-400 shrink-0">
                              · 已涨{sig.intraday_gain > 0 ? "+" : ""}{sig.intraday_gain}%
                            </span>
                          )}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            ) : null}

            {/* 查看全部按钮 */}
            {signals.length > 0 && (
              <Link
                href="/sniper-signals"
                className="mt-3 flex items-center justify-center gap-1.5 py-2 rounded-lg text-xs font-medium text-primary hover:bg-primary/5 transition-colors border border-transparent hover:border-primary/10"
              >
                查看全部信号
                <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                </svg>
              </Link>
            )}
          </>
        )}
      </div>
    </Card>
  );
}
