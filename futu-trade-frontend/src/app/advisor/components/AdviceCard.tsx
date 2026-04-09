// 单条决策建议卡片

"use client";

import type { DecisionAdvice } from "@/types/advisor";
import { AIAnalysisPanel } from "./AIAnalysisPanel";

const URGENCY_STYLES: Record<number, { bg: string; border: string; dot: string }> = {
  10: { bg: "bg-red-50", border: "border-red-300", dot: "bg-red-500" },
  8: { bg: "bg-orange-50", border: "border-orange-300", dot: "bg-orange-500" },
  5: { bg: "bg-yellow-50", border: "border-yellow-300", dot: "bg-yellow-500" },
  1: { bg: "bg-gray-50", border: "border-gray-300", dot: "bg-gray-400" },
};

const URGENCY_LABELS: Record<number, string> = {
  10: "紧急",
  8: "重要",
  5: "建议",
  1: "提示",
};

interface AdviceCardProps {
  advice: DecisionAdvice;
  isSelected: boolean;
  onSelect: (advice: DecisionAdvice) => void;
  onDismiss: (id: string) => void;
  onExecute: (id: string) => void;
  executing: boolean;
}

export function AdviceCard({
  advice,
  isSelected,
  onSelect,
  onDismiss,
  onExecute,
  executing,
}: AdviceCardProps) {
  const style = URGENCY_STYLES[advice.urgency] || URGENCY_STYLES[1];

  return (
    <div
      className={`p-3 rounded-lg border cursor-pointer transition-all ${style.bg} ${style.border} ${
        isSelected ? "ring-2 ring-blue-500" : ""
      }`}
      onClick={() => onSelect(advice)}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <span className={`w-2.5 h-2.5 rounded-full shrink-0 ${style.dot}`} />
          <span className="font-medium text-sm truncate">{advice.title}</span>
        </div>
        <span className="text-xs px-1.5 py-0.5 rounded bg-white/80 shrink-0">
          {URGENCY_LABELS[advice.urgency]}
        </span>
      </div>

      <p className="text-xs text-gray-600 mt-1.5 ml-4.5 line-clamp-2">
        {advice.description}
      </p>

      <div className="flex items-center justify-between mt-2 ml-4.5">
        <span className="text-xs text-gray-400">
          {advice.advice_type_label}
        </span>
        <div className="flex gap-1.5">
          <button
            className="text-xs px-2 py-1 rounded text-gray-500 hover:bg-gray-200 transition-colors"
            onClick={(e) => {
              e.stopPropagation();
              onDismiss(advice.id);
            }}
          >
            忽略
          </button>
          <button
            className="text-xs px-2 py-1 rounded bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50 transition-colors"
            disabled={executing}
            onClick={(e) => {
              e.stopPropagation();
              onExecute(advice.id);
            }}
          >
            {executing ? "执行中..." : "执行"}
          </button>
        </div>
      </div>

      {/* AI 分析面板 */}
      {advice.ai_analysis && (
        <div className="mt-2">
          <AIAnalysisPanel analysis={advice.ai_analysis} />
        </div>
      )}
    </div>
  );
}
