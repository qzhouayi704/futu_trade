// 驾驶舱决策日志 — 信号→决策→执行 全链路追踪

"use client";

import { useState, useEffect } from "react";
import { useSocket } from "@/lib/socket";
import { sniperApi } from "@/lib/api/sniper";

interface PipelineRecord {
  id?: number;
  timestamp: string;
  stock_code: string;
  stock_name: string;
  source: string;
  direction: string;
  strength: number;
  final_action: string;
  final_reason: string;
}

const ACTION_STYLES: Record<string, { emoji: string; color: string }> = {
  executed: { emoji: "✅", color: "text-emerald-500" },
  rejected: { emoji: "❌", color: "text-red-400" },
  skipped: { emoji: "⏭️", color: "text-muted-foreground" },
  pending: { emoji: "⏳", color: "text-amber-500" },
};

const SOURCE_LABELS: Record<string, string> = {
  anomaly: "资金流",
  sniper: "Sniper",
  scalping: "短线",
};

export function DecisionLog() {
  const { socket } = useSocket();
  const [records, setRecords] = useState<PipelineRecord[]>([]);
  const [expanded, setExpanded] = useState(false);

  // 初始加载
  useEffect(() => {
    const load = async () => {
      try {
        const res = await sniperApi.getSignalPipeline(30);
        if (res?.success && Array.isArray(res.data)) {
          setRecords(res.data);
        }
      } catch {}
    };
    load();
    const timer = setInterval(load, 60000);
    return () => clearInterval(timer);
  }, []);

  // WebSocket 实时更新
  useEffect(() => {
    if (!socket) return;
    const handlePipeline = (data: PipelineRecord) => {
      setRecords((prev) => [data, ...prev].slice(0, 50));
    };
    socket.on("signal_pipeline", handlePipeline);
    return () => { socket.off("signal_pipeline", handlePipeline); };
  }, [socket]);

  const displayRecords = expanded ? records : records.slice(0, 5);
  const executedCount = records.filter((r) => r.final_action === "executed").length;
  const rejectedCount = records.filter((r) => r.final_action === "rejected").length;

  return (
    <div className="bg-card/80 backdrop-blur-sm border border-border rounded-xl overflow-hidden">
      {/* 折叠头 */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between px-4 py-2.5 hover:bg-accent/30 transition-colors"
      >
        <span className="text-sm font-semibold text-foreground flex items-center gap-2">
          📋 决策日志
          <span className="text-[10px] font-normal text-muted-foreground">
            ✅{executedCount} ❌{rejectedCount}
          </span>
        </span>
        <svg
          className={`w-4 h-4 text-muted-foreground transition-transform duration-200 ${expanded ? "rotate-180" : ""}`}
          fill="none" viewBox="0 0 24 24" stroke="currentColor"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {/* 内容 */}
      {(expanded || records.length <= 5) && records.length > 0 && (
        <div className="px-4 pb-3 space-y-1">
          {displayRecords.map((rec, idx) => {
            const style = ACTION_STYLES[rec.final_action] || ACTION_STYLES.pending;
            const time = rec.timestamp?.slice(11, 16) || "";
            const sourceLabel = SOURCE_LABELS[rec.source] || rec.source;

            return (
              <div
                key={rec.id || `${rec.timestamp}-${idx}`}
                className="flex items-center gap-2 py-1 text-xs"
              >
                <span className="text-[10px] font-mono tabular-nums text-muted-foreground w-10 shrink-0">
                  {time}
                </span>
                <span>{style.emoji}</span>
                <span className="font-medium text-foreground truncate">
                  {rec.stock_name}
                </span>
                <span className="text-[9px] px-1.5 py-0.5 rounded bg-muted text-muted-foreground shrink-0">
                  {sourceLabel}
                </span>
                <span className={`text-[10px] truncate flex-1 ${style.color}`}>
                  {rec.final_reason}
                </span>
              </div>
            );
          })}

          {!expanded && records.length > 5 && (
            <button
              onClick={() => setExpanded(true)}
              className="text-xs text-primary hover:text-primary/80 font-medium py-1"
            >
              展开全部 {records.length} 条 →
            </button>
          )}
        </div>
      )}

      {records.length === 0 && (
        <div className="px-4 pb-3 text-xs text-muted-foreground text-center py-3">
          暂无决策记录
        </div>
      )}
    </div>
  );
}
