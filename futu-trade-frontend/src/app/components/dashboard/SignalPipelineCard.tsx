// 交易信号流水卡片 — 展示每条信号从产生到决策的完整过程
"use client";

import { useState, useEffect, useCallback } from "react";
import { Card } from "@/components/common";
import { useSocket } from "@/lib/socket";
import apiClient from "@/lib/api/client";

interface ResonanceInfo {
  matched?: boolean;
  type?: string | null;
  reason?: string;
}

interface GuardInfo {
  passed?: boolean;
  reason?: string;
}

interface PipelineRecord {
  id: number;
  timestamp: string;
  stock_code: string;
  stock_name: string;
  source: string;
  direction: string;
  strength: number;
  resonance: ResonanceInfo;
  guard: GuardInfo;
  final_action: string;
  final_reason: string;
}

const ACTION_CONFIG: Record<string, { label: string; bg: string; text: string; icon: string }> = {
  executed: { label: "已执行", bg: "bg-emerald-100", text: "text-emerald-700", icon: "✅" },
  waiting:  { label: "等待中", bg: "bg-amber-100",   text: "text-amber-700",   icon: "⏳" },
  rejected: { label: "已拒绝", bg: "bg-red-100",     text: "text-red-700",     icon: "❌" },
};

const SOURCE_LABELS: Record<string, string> = {
  sniper: "狙击手",
  anomaly: "异动",
  scorer: "评分",
};

export function SignalPipelineCard() {
  const { socket } = useSocket();
  const [records, setRecords] = useState<PipelineRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [expandedId, setExpandedId] = useState<number | null>(null);

  const loadRecords = useCallback(async () => {
    try {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const res: any = await apiClient.get("/sniper/signal-pipeline?limit=30");
      if (res.success && res.data) {
        setRecords(res.data);
      }
    } catch (e) {
      console.error("加载信号流水失败:", e);
    } finally {
      setLoading(false);
    }
  }, []);

  // 初始加载 + 2分钟轮询
  useEffect(() => {
    loadRecords();
    const timer = setInterval(loadRecords, 120000);
    return () => clearInterval(timer);
  }, [loadRecords]);

  // WebSocket 实时推送
  useEffect(() => {
    if (!socket) return;
    const handler = (data: PipelineRecord) => {
      setRecords((prev) => {
        const next = [data, ...prev].slice(0, 50);
        return next;
      });
    };
    socket.on("signal_pipeline", handler);
    return () => { socket.off("signal_pipeline", handler); };
  }, [socket]);

  // 强度条颜色
  const getStrengthColor = (strength: number) => {
    if (strength >= 80) return "bg-red-500";
    if (strength >= 60) return "bg-orange-500";
    if (strength >= 40) return "bg-amber-500";
    return "bg-gray-400";
  };

  const executedCount = records.filter((r) => r.final_action === "executed").length;
  const rejectedCount = records.filter((r) => r.final_action === "rejected").length;

  return (
    <Card>
      <div className="p-4 md:p-5">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-base font-semibold text-gray-900 flex items-center gap-1.5">
            <span className="text-base">🔬</span>
            交易信号追踪
          </h3>
          <div className="flex items-center gap-2">
            {executedCount > 0 && (
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-100 text-emerald-700 font-medium">
                ✅ {executedCount}
              </span>
            )}
            {rejectedCount > 0 && (
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-red-100 text-red-700 font-medium">
                ❌ {rejectedCount}
              </span>
            )}
            <span className="text-[10px] text-gray-400">
              {records.length} 条记录
            </span>
          </div>
        </div>

        {loading ? (
          <div className="text-center py-6 text-gray-400 text-sm">加载中...</div>
        ) : records.length === 0 ? (
          <div className="text-center py-4 text-gray-400 text-sm">
            暂无信号流水记录
          </div>
        ) : (
          <div className="space-y-1.5 max-h-[400px] overflow-y-auto">
            {records.map((item, idx) => {
              const cfg = ACTION_CONFIG[item.final_action] || ACTION_CONFIG.rejected;
              const timeStr = item.timestamp
                ? item.timestamp.slice(11, 16)
                : "";
              const isExpanded = expandedId === (item.id || idx);

              return (
                <div key={item.id || `rt-${idx}`}>
                  <div
                    className={`px-2.5 py-2 rounded-lg border cursor-pointer transition-all hover:shadow-sm ${
                      item.final_action === "executed"
                        ? "bg-emerald-50/60 border-emerald-200/50"
                        : item.final_action === "waiting"
                        ? "bg-amber-50/60 border-amber-200/50"
                        : "bg-red-50/40 border-red-200/40"
                    }`}
                    onClick={() => setExpandedId(isExpanded ? null : (item.id || idx))}
                  >
                    {/* 主行 */}
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-1.5 min-w-0">
                        <span className="text-[10px] font-mono tabular-nums text-gray-400 shrink-0">
                          {timeStr}
                        </span>
                        <span className={`text-[9px] px-1 py-px rounded font-medium shrink-0 ${
                          item.direction === "BUY" ? "bg-emerald-200/60 text-emerald-700" : "bg-red-200/60 text-red-700"
                        }`}>
                          {item.direction === "BUY" ? "买" : "卖"}
                        </span>
                        <span className="font-bold text-xs text-gray-800 truncate">
                          {item.stock_name}
                        </span>
                        <span className="text-[9px] px-1 py-px rounded bg-blue-100/60 text-blue-600 font-medium shrink-0">
                          {SOURCE_LABELS[item.source] || item.source}
                        </span>
                      </div>
                      <div className="flex items-center gap-1.5 shrink-0">
                        {/* 强度条 */}
                        <div className="w-12 h-1.5 bg-gray-200 rounded-full overflow-hidden">
                          <div
                            className={`h-full rounded-full ${getStrengthColor(item.strength)}`}
                            style={{ width: `${Math.min(item.strength, 100)}%` }}
                          />
                        </div>
                        <span className={`text-[9px] px-1.5 py-px rounded font-medium ${cfg.bg} ${cfg.text}`}>
                          {cfg.icon} {cfg.label}
                        </span>
                      </div>
                    </div>

                    {/* 摘要 */}
                    <div className="mt-1 flex items-center gap-1.5">
                      <span className="text-[10px] text-gray-500 truncate">
                        {item.final_reason}
                      </span>
                    </div>
                  </div>

                  {/* 展开详情 */}
                  {isExpanded && (
                    <div className="mx-1 px-3 py-2 bg-gray-50 border border-t-0 border-gray-200 rounded-b-lg text-[11px] space-y-1.5">
                      <div className="grid grid-cols-2 gap-x-4 gap-y-1">
                        <div>
                          <span className="text-gray-400">股票代码：</span>
                          <span className="text-gray-700">{item.stock_code}</span>
                        </div>
                        <div>
                          <span className="text-gray-400">信号强度：</span>
                          <span className="text-gray-700">{item.strength?.toFixed(0)}</span>
                        </div>
                      </div>

                      {/* 共振结果 */}
                      <div className="flex items-center gap-1">
                        <span className={`w-2 h-2 rounded-full shrink-0 ${
                          item.resonance?.matched ? "bg-emerald-500" : "bg-gray-300"
                        }`} />
                        <span className="text-gray-500">共振：</span>
                        <span className="text-gray-700">
                          {item.resonance?.matched
                            ? `✓ ${item.resonance.type || "匹配"}`
                            : `✗ ${item.resonance?.reason || "未匹配"}`}
                        </span>
                      </div>

                      {/* 门卫结果 */}
                      {item.guard && Object.keys(item.guard).length > 0 && (
                        <div className="flex items-center gap-1">
                          <span className={`w-2 h-2 rounded-full shrink-0 ${
                            item.guard?.passed ? "bg-emerald-500" : "bg-red-500"
                          }`} />
                          <span className="text-gray-500">门卫：</span>
                          <span className="text-gray-700">
                            {item.guard?.passed
                              ? "✓ 全部通过"
                              : `✗ ${item.guard?.reason || "被拒绝"}`}
                          </span>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </Card>
  );
}
