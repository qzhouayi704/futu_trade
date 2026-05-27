// 模拟交易记录卡片 — WebSocket 实时 + API 轮询
"use client";

import { useState, useEffect, useCallback } from "react";
import { Card } from "@/components/common";
import { useSocket } from "@/lib/socket";
import apiClient from "@/lib/api/client";

interface SimRecord {
  id: number;
  stock_code: string;
  stock_name: string;
  direction: string;
  price: number;
  quantity: number;
  amount: number;
  resonance_type: string;
  reason: string;
  sources: string;
  created_at: string;
}

interface TradeDecision {
  stock_code: string;
  stock_name: string;
  direction: string;
  price: number;
  quantity: number;
  resonance_type: string;
  reason: string;
  simulated: boolean;
  timestamp?: string;
}

export function SimulatedTradeCard() {
  const { socket } = useSocket();
  const [records, setRecords] = useState<SimRecord[]>([]);
  const [realtimeDecisions, setRealtimeDecisions] = useState<TradeDecision[]>([]);
  const [loading, setLoading] = useState(true);

  // 加载持久化记录
  const loadRecords = useCallback(async () => {
    try {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const res: any = await apiClient.get("/sniper/simulated-trades");
      if (res.success && res.data) {
        setRecords(res.data.records || []);
      }
    } catch (e) {
      console.error("加载模拟交易记录失败:", e);
    } finally {
      setLoading(false);
    }
  }, []);

  // 初始加载 + 5分钟轮询
  useEffect(() => {
    loadRecords();
    const timer = setInterval(loadRecords, 300000);
    return () => clearInterval(timer);
  }, [loadRecords]);

  // WebSocket 实时决策
  useEffect(() => {
    if (!socket) return;
    const handler = (data: TradeDecision) => {
      setRealtimeDecisions((prev) => [data, ...prev].slice(0, 20));
      // 收到新决策后刷新数据库记录
      setTimeout(loadRecords, 1000);
    };
    socket.on("trade_decision", handler);
    return () => { socket.off("trade_decision", handler); };
  }, [socket, loadRecords]);

  const resonanceLabels: Record<string, string> = {
    dual_source: "双源共振",
    strong_single: "强信号",
    multi_green: "多重绿色",
  };

  // 合并展示：实时决策 + 数据库记录
  const allItems = [
    ...realtimeDecisions.map((d, i) => ({
      key: `rt-${i}`,
      stock_name: d.stock_name,
      stock_code: d.stock_code,
      direction: d.direction,
      price: d.price,
      quantity: d.quantity,
      amount: d.price * d.quantity,
      resonance_type: d.resonance_type,
      reason: d.reason,
      created_at: d.timestamp || new Date().toISOString(),
      isRealtime: true,
    })),
    ...records.map((r) => ({
      key: `db-${r.id}`,
      stock_name: r.stock_name,
      stock_code: r.stock_code,
      direction: r.direction,
      price: r.price,
      quantity: r.quantity,
      amount: r.amount,
      resonance_type: r.resonance_type,
      reason: r.reason,
      created_at: r.created_at,
      isRealtime: false,
    })),
  ];

  // 去重（同stock_code+direction+时间前缀）
  const seen = new Set<string>();
  const unique = allItems.filter((item) => {
    const timePrefix = item.created_at?.slice(0, 16) || "";
    const k = `${item.stock_code}:${item.direction}:${timePrefix}`;
    if (seen.has(k)) return false;
    seen.add(k);
    return true;
  }).slice(0, 10);

  return (
    <Card>
      <div className="p-4 md:p-5">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-base font-semibold text-gray-900 flex items-center gap-1.5">
            <span className="text-base">📋</span>
            模拟交易记录
          </h3>
          <span className="text-[10px] text-gray-400">
            {records.length} 条历史记录
          </span>
        </div>

        {loading ? (
          <div className="text-center py-6 text-gray-400 text-sm">加载中...</div>
        ) : unique.length === 0 ? (
          <div className="text-center py-4 text-gray-400 text-sm">
            暂无模拟交易记录
          </div>
        ) : (
          <div className="space-y-1.5">
            {unique.map((item) => {
              const isBuy = item.direction === "BUY";
              const bgColor = isBuy
                ? "bg-emerald-50/60 border-emerald-200/50"
                : "bg-red-50/60 border-red-200/50";
              const textColor = isBuy ? "text-emerald-600" : "text-red-600";
              const dirLabel = isBuy ? "买入" : "卖出";
              const timeStr = item.created_at
                ? new Date(item.created_at).toLocaleString("zh-CN", {
                    month: "2-digit", day: "2-digit",
                    hour: "2-digit", minute: "2-digit",
                  })
                : "";

              return (
                <div
                  key={item.key}
                  className={`px-2.5 py-2 rounded-lg border ${bgColor}`}
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-1.5 min-w-0">
                      <span className="text-[10px] font-mono tabular-nums text-gray-400 shrink-0">
                        {timeStr}
                      </span>
                      <span className={`text-xs font-bold ${textColor}`}>
                        {isBuy ? "🟢" : "🔴"} {dirLabel}
                      </span>
                      <span className="font-bold text-xs text-gray-800 truncate">
                        {item.stock_name}
                      </span>
                      {item.isRealtime && (
                        <span className="text-[9px] px-1 py-px rounded bg-blue-200/60 text-blue-700 font-medium shrink-0">
                          实时
                        </span>
                      )}
                    </div>
                    <div className="flex items-center gap-1.5 shrink-0">
                      <span className="text-xs font-bold tabular-nums text-gray-600">
                        {item.price.toFixed(3)}
                      </span>
                      <span className="text-[10px] text-gray-400">
                        x{item.quantity}
                      </span>
                    </div>
                  </div>
                  <div className="flex items-center gap-1.5 mt-1">
                    {item.resonance_type && (
                      <span className="text-[9px] px-1 py-px rounded bg-purple-200/60 text-purple-700 font-medium">
                        {resonanceLabels[item.resonance_type] || item.resonance_type}
                      </span>
                    )}
                    <span className={`text-[10px] ${textColor} opacity-70 truncate`}>
                      {item.reason}
                    </span>
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
