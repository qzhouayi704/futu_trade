// AI 分析师意见面板
"use client";

import type { AIAnalysis, AnalystAction } from "@/types/advisor";

const ACTION_LABELS: Record<AnalystAction, string> = {
  STRONG_BUY: "强烈买入",
  BUY: "买入",
  HOLD: "持有",
  REDUCE: "减仓",
  SELL: "卖出",
  STRONG_SELL: "强烈卖出",
  WAIT: "观望",
};

const ACTION_COLORS: Record<AnalystAction, string> = {
  STRONG_BUY: "bg-red-100 text-red-700",
  BUY: "bg-red-50 text-red-600",
  HOLD: "bg-gray-100 text-gray-600",
  REDUCE: "bg-green-50 text-green-600",
  SELL: "bg-green-100 text-green-700",
  STRONG_SELL: "bg-green-200 text-green-800",
  WAIT: "bg-yellow-50 text-yellow-600",
};

const ALIGNMENT_LABELS: Record<string, string> = {
  Confirming: "资金确认",
  Diverging: "资金背离",
  Unclear: "不明确",
};

interface AIAnalysisPanelProps {
  analysis: AIAnalysis;
}

export function AIAnalysisPanel({ analysis }: AIAnalysisPanelProps) {
  const action = analysis.action as AnalystAction;
  const scoreColor =
    analysis.alpha_signal_score > 0.3
      ? "text-red-600"
      : analysis.alpha_signal_score < -0.3
        ? "text-green-600"
        : "text-gray-600";

  return (
    <div className="p-4 rounded-lg bg-purple-50 border border-purple-200">
      {/* 头部 */}
      <div className="flex items-center gap-2 mb-3">
        <span className="text-lg">🤖</span>
        <span className="font-medium text-sm text-purple-800">
          AI 分析师意见
        </span>
        <span
          className={`px-2 py-0.5 rounded text-xs font-medium ${ACTION_COLORS[action] || "bg-gray-100"}`}
        >
          {ACTION_LABELS[action] || action}
        </span>
        <span className="text-xs text-purple-500 ml-auto">
          置信度 {(analysis.confidence * 100).toFixed(0)}%
        </span>
      </div>

      {/* 核心指标 */}
      <div className="grid grid-cols-3 gap-2 mb-3 text-xs">
        <div className="bg-white/60 rounded px-2 py-1">
          <span className="text-gray-500">催化剂:</span>{" "}
          <span className="font-medium">{analysis.catalyst_impact}</span>
        </div>
        <div className="bg-white/60 rounded px-2 py-1">
          <span className="text-gray-500">资金:</span>{" "}
          <span className="font-medium">
            {ALIGNMENT_LABELS[analysis.smart_money_alignment] ||
              analysis.smart_money_alignment}
          </span>
        </div>
        <div className="bg-white/60 rounded px-2 py-1">
          <span className="text-gray-500">Alpha:</span>{" "}
          <span className={`font-medium ${scoreColor}`}>
            {analysis.alpha_signal_score > 0 ? "+" : ""}
            {analysis.alpha_signal_score.toFixed(2)}
          </span>
        </div>
      </div>

      {/* 分析理由 */}
      <p className="text-sm text-gray-700 mb-2">{analysis.reasoning}</p>

      {/* 关键因素 */}
      {analysis.key_factors && analysis.key_factors.length > 0 && (
        <div className="flex flex-wrap gap-1 mb-2">
          {analysis.key_factors.map((factor, i) => (
            <span
              key={i}
              className="text-xs px-2 py-0.5 bg-purple-100 text-purple-700 rounded"
            >
              {factor}
            </span>
          ))}
        </div>
      )}

      {/* 风险提示 */}
      {analysis.risk_warning && (
        <p className="text-xs text-orange-600 mt-1">
          ⚠️ {analysis.risk_warning}
        </p>
      )}

      {/* 目标价/止损价 */}
      {(analysis.target_price || analysis.stop_loss_price) && (
        <div className="flex gap-4 mt-2 text-xs text-gray-500">
          {analysis.target_price && (
            <span>
              目标价: <span className="text-red-600">{analysis.target_price}</span>
            </span>
          )}
          {analysis.stop_loss_price && (
            <span>
              止损价:{" "}
              <span className="text-green-600">{analysis.stop_loss_price}</span>
            </span>
          )}
        </div>
      )}
    </div>
  );
}
