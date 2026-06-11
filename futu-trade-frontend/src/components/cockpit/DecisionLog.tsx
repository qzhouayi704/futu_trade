// 驾驶舱决策日志 — 信号→决策→执行 全链路追踪

"use client";

"use client";

import { useState, useEffect } from "react";
import { useSocket } from "@/lib/socket";
import { sniperApi } from "@/lib/api/sniper";
import apiClient from "@/lib/api/client";

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
  broadcast: { emoji: "📡", color: "text-blue-500" },
  rejected: { emoji: "❌", color: "text-rose-500" },
  waiting: { emoji: "⏳", color: "text-amber-500" },
  skipped: { emoji: "⏭️", color: "text-muted-foreground" },
  pending: { emoji: "⏳", color: "text-amber-500" },
};

const SOURCE_LABELS: Record<string, string> = {
  anomaly: "资金流",
  sniper: "Sniper",
  scalping: "短线",
  strategy: "策略",
  absorption_scanner: "量价",
  capital_flow: "资金流",
  intraday_profit: "日内",
  intraday_risk: "风控",
};

export function DecisionLog() {
  const { socket } = useSocket();
  const [executedRecords, setExecutedRecords] = useState<PipelineRecord[]>([]);
  const [rejectedRecords, setRejectedRecords] = useState<PipelineRecord[]>([]);
  const [activeTab, setActiveTab] = useState<"executed" | "rejected">("executed");
  const [expanded, setExpanded] = useState(false);

  // 初始加载及轮询
  useEffect(() => {
    const load = async () => {
      try {
        const [executedRes, rejectedRes]: any[] = await Promise.all([
          sniperApi.getSignalPipeline(30),
          apiClient.get("/signals/rejected?limit=30")
        ]);
        if (executedRes?.success && Array.isArray(executedRes.data)) {
          setExecutedRecords(executedRes.data);
        }
        if (rejectedRes?.success && Array.isArray(rejectedRes.data)) {
          setRejectedRecords(rejectedRes.data);
        }
      } catch (e) {
        console.error("加载决策/拦截日志失败:", e);
      }
    };
    load();
    const timer = setInterval(load, 30000);
    return () => clearInterval(timer);
  }, []);

  // WebSocket 实时更新
  useEffect(() => {
    if (!socket) return;
    const handlePipeline = (data: PipelineRecord) => {
      if (data.final_action === "rejected") {
        setRejectedRecords((prev) => [data, ...prev].slice(0, 50));
      } else {
        setExecutedRecords((prev) => [data, ...prev].slice(0, 50));
      }
    };
    socket.on("signal_pipeline", handlePipeline);
    return () => { socket.off("signal_pipeline", handlePipeline); };
  }, [socket]);

  const currentRecords = activeTab === "executed" ? executedRecords : rejectedRecords;
  const displayRecords = expanded ? currentRecords : currentRecords.slice(0, 5);
  const executedCount = executedRecords.filter((r) => r.final_action === "executed" || r.final_action === "broadcast").length;
  const rejectedCount = rejectedRecords.length;

  return (
    <div className="bg-card/80 backdrop-blur-sm border border-border rounded-xl overflow-hidden">
      {/* 折叠头 */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between px-4 py-2.5 hover:bg-accent/30 transition-colors border-b border-border/30"
      >
        <span className="text-sm font-semibold text-foreground flex items-center gap-2">
          📋 决策与拦截日志
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

      {/* 选项卡 */}
      <div className="flex border-b border-border/30 px-4 py-1.5 bg-muted/10">
        <button
          onClick={() => setActiveTab("executed")}
          className={`pb-1 text-xs font-bold mr-4 border-b-2 transition-all ${
            activeTab === "executed"
              ? "border-primary text-primary"
              : "border-transparent text-muted-foreground hover:text-foreground"
          }`}
        >
          已执行 ({executedCount})
        </button>
        <button
          onClick={() => setActiveTab("rejected")}
          className={`pb-1 text-xs font-bold border-b-2 transition-all ${
            activeTab === "rejected"
              ? "border-primary text-primary"
              : "border-transparent text-muted-foreground hover:text-foreground"
          }`}
        >
          被拦截 ({rejectedCount})
        </button>
      </div>

      {/* 内容 */}
      {(expanded || currentRecords.length <= 5) && currentRecords.length > 0 && (
        <div className="px-4 py-2 space-y-1">
          {displayRecords.map((rec, idx) => {
            const style = ACTION_STYLES[rec.final_action] || ACTION_STYLES.pending;
            const time = rec.timestamp?.slice(11, 16) || "";
            const sourceLabel = SOURCE_LABELS[rec.source] || rec.source;

            // 针对被拦截记录的定制红色/橙色高亮
            const isRejected = rec.final_action === "rejected" || activeTab === "rejected";
            const isCooldownOrTrap = rec.final_reason?.includes("冷却") || 
                                     rec.final_reason?.includes("cooldown") || 
                                     rec.final_reason?.includes("限频") || 
                                     rec.final_reason?.includes("trap") || 
                                     rec.final_reason?.includes("陷阱") ||
                                     rec.final_reason?.includes("Filter");
            
            const reasonColor = isCooldownOrTrap 
              ? "text-amber-600 dark:text-amber-400 font-medium bg-amber-500/5 px-1 rounded" 
              : "text-rose-600 dark:text-rose-400 font-medium bg-rose-500/5 px-1 rounded";

            return (
              <div
                key={rec.id || `${rec.timestamp}-${idx}`}
                className="flex items-center gap-2 py-1 text-xs hover:bg-muted/10 rounded transition-colors"
              >
                <span className="text-[10px] font-mono tabular-nums text-muted-foreground w-10 shrink-0">
                  {time}
                </span>
                <span>{isRejected ? "❌" : style.emoji}</span>
                <span className="font-semibold text-foreground truncate w-24 shrink-0">
                  {rec.stock_name}
                </span>
                <span className="text-[9px] px-1.5 py-0.5 rounded bg-muted text-muted-foreground shrink-0 font-medium">
                  {sourceLabel}
                </span>
                <span className={`text-[10px] truncate flex-1 ${isRejected ? reasonColor : style.color}`}>
                  {rec.final_reason}
                </span>
              </div>
            );
          })}

          {!expanded && currentRecords.length > 5 && (
            <button
              onClick={() => setExpanded(true)}
              className="text-xs text-primary hover:text-primary/80 font-medium py-1 block mt-1"
            >
              展开全部 {currentRecords.length} 条 →
            </button>
          )}
        </div>
      )}

      {currentRecords.length === 0 && (
        <div className="px-4 py-8 text-xs text-muted-foreground text-center">
          暂无{activeTab === "executed" ? "已执行" : "被拦截"}记录
        </div>
      )}
    </div>
  );
}
