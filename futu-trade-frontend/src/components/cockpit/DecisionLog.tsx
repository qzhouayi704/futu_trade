// 驾驶舱决策日志 — 信号→决策→执行 全链路追踪（v4.0 独立流水线面板）

"use client";

import { useState, useEffect, useMemo } from "react";
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

type TabKey = "all" | "executed" | "rejected" | "waiting" | "cooldown";

const TABS: { key: TabKey; label: string; emoji: string }[] = [
  { key: "all", label: "全部", emoji: "📋" },
  { key: "executed", label: "已执行", emoji: "✅" },
  { key: "rejected", label: "拦截", emoji: "❌" },
  { key: "waiting", label: "等待", emoji: "⏳" },
  { key: "cooldown", label: "冷却", emoji: "🚫" },
];

const ACTION_STYLES: Record<string, { emoji: string; color: string }> = {
  executed: { emoji: "✅", color: "text-emerald-500" },
  broadcast: { emoji: "📡", color: "text-blue-500" },
  rejected: { emoji: "❌", color: "text-rose-500" },
  waiting: { emoji: "⏳", color: "text-amber-500" },
  skipped: { emoji: "⏭️", color: "text-muted-foreground" },
  pending: { emoji: "⏳", color: "text-amber-500" },
  cooldown: { emoji: "🚫", color: "text-slate-400" },
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
  momentum_engine: "动量引擎",
  stock_scorer: "V2评分",
};

/** 判断 final_action 属于哪个 Tab 类别 */
function classifyAction(action: string, reason: string): TabKey {
  if (action === "executed" || action === "broadcast") return "executed";
  if (action === "rejected") {
    // 区分冷却期拦截 vs 门卫拦截
    const isCooldown =
      reason?.includes("冷却") ||
      reason?.includes("cooldown") ||
      reason?.includes("限频") ||
      reason?.includes("频率");
    return isCooldown ? "cooldown" : "rejected";
  }
  if (action === "waiting" || action === "pending") return "waiting";
  return "rejected";
}

export function DecisionLog() {
  const { socket } = useSocket();
  const [allRecords, setAllRecords] = useState<PipelineRecord[]>([]);
  const [activeTab, setActiveTab] = useState<TabKey>("all");
  const [expanded, setExpanded] = useState(false);

  // 初始加载及轮询
  useEffect(() => {
    const load = async () => {
      try {
        const [executedRes, rejectedRes]: any[] = await Promise.all([
          sniperApi.getSignalPipeline(50),
          apiClient.get("/signals/rejected?limit=50"),
        ]);
        const records: PipelineRecord[] = [];
        if (executedRes?.success && Array.isArray(executedRes.data)) {
          records.push(...executedRes.data);
        }
        if (rejectedRes?.success && Array.isArray(rejectedRes.data)) {
          records.push(...rejectedRes.data);
        }
        // 按时间倒序
        records.sort(
          (a, b) =>
            new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime()
        );
        setAllRecords(records);
      } catch (e) {
        console.error("加载决策日志失败:", e);
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
      setAllRecords((prev) => [data, ...prev].slice(0, 100));
    };
    socket.on("signal_pipeline", handlePipeline);
    return () => {
      socket.off("signal_pipeline", handlePipeline);
    };
  }, [socket]);

  // 按 Tab 过滤
  const filteredRecords = useMemo(() => {
    if (activeTab === "all") return allRecords;
    return allRecords.filter(
      (r) => classifyAction(r.final_action, r.final_reason) === activeTab
    );
  }, [allRecords, activeTab]);

  const displayRecords = expanded
    ? filteredRecords
    : filteredRecords.slice(0, 8);

  // 各类计数
  const counts = useMemo(() => {
    const c: Record<TabKey, number> = {
      all: allRecords.length,
      executed: 0,
      rejected: 0,
      waiting: 0,
      cooldown: 0,
    };
    allRecords.forEach((r) => {
      const cat = classifyAction(r.final_action, r.final_reason);
      c[cat]++;
    });
    return c;
  }, [allRecords]);

  /** 拦截原因的颜色样式 */
  const getReasonStyle = (rec: PipelineRecord) => {
    const reason = rec.final_reason || "";
    const action = rec.final_action;

    if (action === "executed" || action === "broadcast") {
      return "text-emerald-600 dark:text-emerald-400";
    }

    // 门卫拦截分类高亮
    if (reason.includes("陷阱") || reason.includes("trap") || reason.includes("Filter")) {
      return "text-rose-600 dark:text-rose-400 font-medium bg-rose-500/5 px-1 rounded";
    }
    if (reason.includes("冷却") || reason.includes("cooldown") || reason.includes("限频")) {
      return "text-amber-600 dark:text-amber-400 font-medium bg-amber-500/5 px-1 rounded";
    }
    if (reason.includes("否决") || reason.includes("veto") || reason.includes("亏损")) {
      return "text-orange-600 dark:text-orange-400 font-medium bg-orange-500/5 px-1 rounded";
    }
    if (reason.includes("等待") || reason.includes("共振")) {
      return "text-sky-600 dark:text-sky-400 font-medium";
    }

    return "text-rose-600 dark:text-rose-400";
  };

  return (
    <div className="bg-card/80 backdrop-blur-sm border border-border rounded-xl overflow-hidden">
      {/* 头栏 */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between px-4 py-2.5 hover:bg-accent/30 transition-colors border-b border-border/30"
      >
        <span className="text-sm font-semibold text-foreground flex items-center gap-2">
          🎯 决策流水线
          <span className="text-[10px] font-normal text-muted-foreground">
            ✅{counts.executed} ❌{counts.rejected} ⏳{counts.waiting} 🚫
            {counts.cooldown}
          </span>
        </span>
        <svg
          className={`w-4 h-4 text-muted-foreground transition-transform duration-200 ${
            expanded ? "rotate-180" : ""
          }`}
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d="M19 9l-7 7-7-7"
          />
        </svg>
      </button>

      {/* 5 Tab */}
      <div className="flex border-b border-border/30 px-3 py-1.5 bg-muted/10 gap-0.5 overflow-x-auto">
        {TABS.map((tab) => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key)}
            className={`px-2.5 py-1 text-[10px] font-bold rounded-md transition-all shrink-0 ${
              activeTab === tab.key
                ? "bg-primary/15 text-primary border border-primary/20"
                : "text-muted-foreground hover:text-foreground hover:bg-muted/50"
            }`}
          >
            {tab.emoji}{" "}
            {tab.label}
            {counts[tab.key] > 0 && (
              <span className="ml-0.5 text-[9px] opacity-70">
                ({counts[tab.key]})
              </span>
            )}
          </button>
        ))}
      </div>

      {/* 内容 */}
      {filteredRecords.length > 0 ? (
        <div className="px-4 py-2 space-y-0.5">
          {displayRecords.map((rec, idx) => {
            const style =
              ACTION_STYLES[rec.final_action] || ACTION_STYLES.pending;
            const time = rec.timestamp?.slice(11, 16) || "";
            const sourceLabel = SOURCE_LABELS[rec.source] || rec.source;
            const category = classifyAction(
              rec.final_action,
              rec.final_reason
            );
            const categoryEmoji =
              category === "executed"
                ? "✅"
                : category === "rejected"
                  ? "❌"
                  : category === "waiting"
                    ? "⏳"
                    : category === "cooldown"
                      ? "🚫"
                      : style.emoji;

            return (
              <div
                key={rec.id || `${rec.timestamp}-${idx}`}
                className="flex items-start gap-2 py-1.5 text-xs hover:bg-muted/10 rounded transition-colors"
              >
                {/* 时间 */}
                <span className="text-[10px] font-mono tabular-nums text-muted-foreground w-10 shrink-0 pt-0.5">
                  {time}
                </span>
                {/* 状态 emoji */}
                <span className="pt-0.5">{categoryEmoji}</span>
                {/* 股票名 */}
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-1.5">
                    <span className="font-semibold text-foreground truncate">
                      {rec.stock_name}
                    </span>
                    {/* 通道标签 */}
                    <span className="text-[9px] px-1.5 py-0.5 rounded bg-muted text-muted-foreground shrink-0 font-medium">
                      {sourceLabel}
                    </span>
                    {/* 强度 */}
                    {rec.strength > 0 && (
                      <span className="text-[9px] text-muted-foreground font-mono">
                        ★{rec.strength}
                      </span>
                    )}
                  </div>
                  {/* 原因/详情 — 第二行 */}
                  {rec.final_reason && (
                    <div
                      className={`text-[10px] mt-0.5 leading-snug truncate ${getReasonStyle(rec)}`}
                    >
                      {rec.final_reason}
                    </div>
                  )}
                </div>
              </div>
            );
          })}

          {!expanded && filteredRecords.length > 8 && (
            <button
              onClick={() => setExpanded(true)}
              className="text-xs text-primary hover:text-primary/80 font-medium py-1 block mt-1"
            >
              展开全部 {filteredRecords.length} 条 →
            </button>
          )}
        </div>
      ) : (
        <div className="px-4 py-8 text-xs text-muted-foreground text-center">
          暂无
          {activeTab === "all"
            ? ""
            : TABS.find((t) => t.key === activeTab)?.label}
          记录
        </div>
      )}
    </div>
  );
}
