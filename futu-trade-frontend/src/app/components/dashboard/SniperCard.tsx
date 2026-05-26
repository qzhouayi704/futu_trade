// 盘中狙击手 — 实时信号卡片
// 通过 WebSocket 接收实时信号 + API 轮询兜底

"use client";

import { useState, useEffect, useCallback } from "react";
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

export function SniperCard() {
  const { socket } = useSocket();
  const [signals, setSignals] = useState<SniperSignal[]>([]);
  const [loading, setLoading] = useState(true);
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);

  // API 加载信号
  const loadSignals = useCallback(async () => {
    try {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const res: any = await apiClient.get("/sniper/signals");
      if (res.success && Array.isArray(res.data)) {
        setSignals(res.data);
        setLastUpdate(new Date());
      }
    } catch (e) {
      console.error("加载狙击手信号失败:", e);
    } finally {
      setLoading(false);
    }
  }, []);

  // 初始加载 + 3分钟轮询
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
        // 去重：同股票同类信号保留最新
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

  // 统计
  const reds = signals.filter((s) => s.is_red);
  const greens = signals.filter((s) => !s.is_red);

  // 只展示最近 10 条
  const recent = [...signals]
    .sort((a, b) => b.time.localeCompare(a.time))
    .slice(0, 10);

  return (
    <Card>
      <div className="p-4 md:p-5">
        {/* 标题栏 */}
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-base font-semibold text-gray-900 flex items-center gap-1.5">
            <span className="text-base">🎯</span>
            盘中狙击
            {reds.length > 0 && (
              <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-red-100 text-red-700 font-medium animate-pulse">
                {reds.length} 风险
              </span>
            )}
            {greens.length > 0 && (
              <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-emerald-100 text-emerald-700 font-medium">
                {greens.length} 机会
              </span>
            )}
          </h3>
          <span className="text-[10px] text-gray-400">
            {lastUpdate ? `${lastUpdate.toLocaleTimeString("zh-CN")} 更新` : ""}
          </span>
        </div>

        {loading ? (
          <div className="text-center py-6 text-gray-400 text-sm">扫描中...</div>
        ) : signals.length === 0 ? (
          <div className="text-center py-6 text-gray-400 text-sm">
            暂无信号 — 引擎每3分钟扫描一次
          </div>
        ) : (
          <div className="space-y-1.5">
            {recent.map((sig, idx) => {
              const bgColor = sig.is_red
                ? sig.severity === "high"
                  ? "bg-red-50/80 border-red-200/60"
                  : "bg-orange-50/80 border-orange-200/60"
                : sig.severity === "high"
                  ? "bg-emerald-50/80 border-emerald-200/60"
                  : "bg-blue-50/80 border-blue-200/60";

              const textColor = sig.is_red
                ? "text-red-600"
                : "text-emerald-600";

              const badgeColor = sig.is_red
                ? "bg-red-200/80 text-red-700"
                : "bg-emerald-200/80 text-emerald-700";

              const typeLabels: Record<string, string> = {
                mega_sell: "巨量砸盘",
                mega_buy: "巨量抢筹",
                reversal_bear: "资金转负",
                reversal_bull: "资金转正",
                accel_in: "资金加速",
                sustained_out: "持续流出",
              };

              return (
                <div
                  key={`${sig.stock_code}-${sig.signal_type}-${sig.time}-${idx}`}
                  className={`px-2.5 py-2 rounded-lg border ${bgColor} transition-all hover:shadow-sm`}
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-1.5 min-w-0">
                      <span className={`text-xs font-mono tabular-nums text-gray-400 shrink-0`}>
                        {sig.time}
                      </span>
                      <span className={`text-xs ${sig.is_red ? "animate-pulse" : ""}`}>
                        {sig.emoji}
                      </span>
                      <span className={`font-bold text-xs ${textColor} truncate`}>
                        {sig.stock_name}
                      </span>
                      <span className={`text-[9px] px-1 py-px rounded font-medium shrink-0 ${badgeColor}`}>
                        {typeLabels[sig.signal_type] || sig.signal_type}
                      </span>
                    </div>
                    <span className="text-xs font-bold tabular-nums text-gray-600 shrink-0 ml-2">
                      {sig.price.toFixed(3)}
                    </span>
                  </div>
                  <div className={`text-[10px] ${textColor} opacity-75 mt-0.5 flex items-center justify-between`}>
                    <span className="truncate">{sig.detail}</span>
                    <span className="text-gray-400 shrink-0 ml-2">{sig.action}</span>
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
