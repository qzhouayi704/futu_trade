// 逐笔成交洞察组件 - 主编排组件
// 展示当前价位的支撑/阻力和买卖力量

"use client";

import { useState, useEffect, useCallback } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";
import { getTickerAnalysis } from "@/lib/api/enhanced-heat";
import type { TickerAnalysisData } from "@/types/enhanced-heat";

import { ScoreBar } from "./ticker-insight/ScoreBar";
import { ClusterSection } from "./ticker-insight/ClusterSection";
import { ActiveBuySellSummary } from "./ticker-insight/ActiveBuySellSummary";
import { CredibilitySummary } from "./ticker-insight/CredibilitySummary";
import { HelpModal } from "./ticker-insight/HelpModal";

interface TickerInsightProps {
  stockCode: string | null;
}

const SIGNAL_COLORS: Record<string, string> = {
  bullish: "text-red-400",
  slightly_bullish: "text-red-300",
  neutral: "text-gray-400",
  slightly_bearish: "text-green-300",
  bearish: "text-green-400",
};

const SIGNAL_LABELS: Record<string, string> = {
  bullish: "强多",
  slightly_bullish: "偏多",
  neutral: "中性",
  slightly_bearish: "偏空",
  bearish: "强空",
};

// localStorage keys
const STORAGE_KEY_DETAIL = "ticker-insight-detail-expanded";
const STORAGE_KEY_CLUSTER = "ticker-insight-cluster-expanded";

/** 读取 localStorage 折叠状态 */
function getStoredExpanded(key: string, defaultVal: boolean): boolean {
  if (typeof window === "undefined") return defaultVal;
  try {
    const v = localStorage.getItem(key);
    if (v === null) return defaultVal;
    return v === "true";
  } catch {
    return defaultVal;
  }
}

/** 可折叠区块 */
function CollapsibleSection({
  title,
  storageKey,
  defaultExpanded = true,
  children,
}: {
  title: string;
  storageKey: string;
  defaultExpanded?: boolean;
  children: React.ReactNode;
}) {
  const [expanded, setExpanded] = useState(() =>
    getStoredExpanded(storageKey, defaultExpanded),
  );

  const toggle = useCallback(() => {
    setExpanded((prev) => {
      const next = !prev;
      try {
        localStorage.setItem(storageKey, String(next));
      } catch { /* noop */ }
      return next;
    });
  }, [storageKey]);

  return (
    <div>
      <button
        onClick={toggle}
        className="flex items-center justify-between w-full text-xs text-gray-400 hover:text-gray-200 transition-colors py-1"
        aria-expanded={expanded}
        aria-label={`${expanded ? "折叠" : "展开"} ${title}`}
      >
        <span className="font-medium">{title}</span>
        {expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
      </button>
      <div
        className={`overflow-hidden transition-all duration-300 ease-in-out ${expanded ? "max-h-[800px] opacity-100 mt-1" : "max-h-0 opacity-0"
          }`}
      >
        {children}
      </div>
    </div>
  );
}

/** 骨架屏 */
function Skeleton() {
  return (
    <div className="space-y-2 animate-pulse">
      <div className="h-12 bg-gray-700/50 rounded" />
      <div className="h-8 bg-gray-700/50 rounded" />
      <div className="h-8 bg-gray-700/50 rounded" />
      <div className="h-16 bg-gray-700/50 rounded" />
    </div>
  );
}

/** 逐笔成交洞察组件 */
export default function TickerInsight({ stockCode }: TickerInsightProps) {
  const [data, setData] = useState<TickerAnalysisData | null>(null);
  const [loading, setLoading] = useState(false);

  const loadData = useCallback(async (code: string) => {
    setLoading(true);
    try {
      const res = await getTickerAnalysis(code);
      setData(res.success ? res.data : null);
    } catch {
      setData(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (stockCode) {
      loadData(stockCode);
    } else {
      setData(null);
    }
  }, [stockCode, loadData]);

  if (loading) return <Skeleton />;

  if (!data) {
    return (
      <div className="text-center text-gray-500 text-sm py-6 bg-gray-800/30 rounded">
        逐笔成交数据暂不可用
      </div>
    );
  }

  // 找到各维度
  const activeDim = data.dimensions.find((d) => d.name === "主动买卖");
  const clusterDim = data.dimensions.find((d) => d.name === "密集价位");
  const rhythmDim = data.dimensions.find((d) => d.name === "成交节奏");
  const credibilityDim = data.dimensions.find((d) => d.name === "量能可信度");

  const signalColor = SIGNAL_COLORS[data.signal] ?? "text-gray-400";
  const signalLabel = SIGNAL_LABELS[data.signal] ?? "中性";

  // 诱多警告
  const trapWarning = credibilityDim?.details?.trap_warning as
    | string
    | undefined;

  return (
    <div className="space-y-3">
      {/* ===== 综合信号区（顶部，始终显示） ===== */}
      <div className="flex items-center justify-between bg-gray-800/50 rounded p-3">
        <div className="flex items-center gap-2">
          <span className="text-xs text-gray-400">成交面信号</span>
          <span className={`text-xl font-bold ${signalColor}`}>
            {signalLabel}
          </span>
          <HelpModal />
        </div>
        <div className="text-right">
          <span className="text-[10px] text-gray-500">综合评分</span>
          <div className={`text-sm font-medium ${signalColor}`}>
            {data.total_score > 0 ? "+" : ""}
            {data.total_score.toFixed(0)}
          </div>
        </div>
      </div>

      {/* 诱多/诱空警告 */}
      {trapWarning && (
        <div className="bg-orange-900/30 border border-orange-500/40 rounded p-2 text-xs text-orange-300">
          ⚠️ {trapWarning}
        </div>
      )}

      {/* ===== 详细分析区（中部，可折叠） ===== */}
      <CollapsibleSection
        title="详细分析"
        storageKey={STORAGE_KEY_DETAIL}
        defaultExpanded={true}
      >
        <div className="space-y-2">
          {/* 量能可信度 */}
          {credibilityDim && <CredibilitySummary dim={credibilityDim} />}

          {/* 主动买卖力量 */}
          {activeDim && <ActiveBuySellSummary dim={activeDim} />}

          {/* 各维度评分 */}
          <div className="space-y-1">
            {data.dimensions.map((dim) => (
              <ScoreBar key={dim.name} score={dim.score} label={dim.name} />
            ))}
          </div>

          {/* 成交节奏 */}
          {rhythmDim && (
            <div className="text-xs text-gray-500 text-center">
              {rhythmDim.description}
            </div>
          )}
        </div>
      </CollapsibleSection>

      {/* ===== 价位分析区（底部，可折叠） ===== */}
      {clusterDim && (
        <CollapsibleSection
          title="成交密集价位"
          storageKey={STORAGE_KEY_CLUSTER}
          defaultExpanded={true}
        >
          <ClusterSection dim={clusterDim} />
        </CollapsibleSection>
      )}

      {/* 摘要 */}
      <div className="text-xs text-gray-500 bg-gray-800/30 rounded p-2">
        {data.summary}
      </div>
    </div>
  );
}
