// 成交方向标签组件
// 根据 TickerSummary 的 bias 字段显示对应颜色的标签，支持 tooltip 和骨架屏

"use client";

import { useState, useRef } from "react";
import type { TickerSummary } from "@/types/stock";

interface TradeDirectionBadgeProps {
  /** 成交分析摘要，null 表示数据不可用 */
  summary: TickerSummary | null;
  /** 是否正在加载 */
  loading?: boolean;
}

/** bias → 样式映射 */
const BIAS_STYLES: Record<string, { bg: string; text: string }> = {
  strong_bullish: { bg: "bg-red-500", text: "text-white" },
  bullish: { bg: "bg-red-100", text: "text-red-700" },
  bearish: { bg: "bg-green-100", text: "text-green-700" },
  neutral: { bg: "bg-gray-100", text: "text-gray-500" },
};

/** 格式化净额为万元 */
function formatNetTurnover(value: number): string {
  if (Math.abs(value) >= 1_0000_0000) {
    return (value / 1_0000_0000).toFixed(2) + "亿";
  }
  if (Math.abs(value) >= 1_0000) {
    return (value / 1_0000).toFixed(1) + "万";
  }
  return value.toFixed(2);
}

export default function TradeDirectionBadge({
  summary,
  loading,
}: TradeDirectionBadgeProps) {
  const [showTooltip, setShowTooltip] = useState(false);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // 骨架屏
  if (loading) {
    return (
      <span className="inline-block w-10 h-5 bg-gray-200 rounded animate-pulse" />
    );
  }

  // 数据不可用
  if (!summary) {
    return <span className="text-gray-400">-</span>;
  }

  const style = BIAS_STYLES[summary.bias] ?? BIAS_STYLES.neutral;

  const handleMouseEnter = () => {
    if (timeoutRef.current) clearTimeout(timeoutRef.current);
    setShowTooltip(true);
  };

  const handleMouseLeave = () => {
    timeoutRef.current = setTimeout(() => setShowTooltip(false), 150);
  };

  return (
    <span
      className="relative inline-block"
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
    >
      <span
        className={`inline-block px-2 py-0.5 rounded text-xs font-medium cursor-help ${style.bg} ${style.text}`}
      >
        {summary.bias_label}
      </span>

      {/* Tooltip */}
      {showTooltip && (
        <div className="absolute z-50 bottom-full left-1/2 -translate-x-1/2 mb-2 w-48 px-3 py-2 bg-gray-800 text-white text-xs rounded shadow-lg pointer-events-none">
          <div className="flex justify-between mb-1">
            <span className="text-gray-300">综合评分</span>
            <span className="font-medium">{summary.score.toFixed(1)}</span>
          </div>
          <div className="flex justify-between mb-1">
            <span className="text-gray-300">力量比</span>
            <span className="font-medium">{summary.buy_sell_ratio.toFixed(2)}</span>
          </div>
          <div className="flex justify-between mb-1">
            <span className="text-gray-300">主动买卖净额</span>
            <span className="font-medium">{formatNetTurnover(summary.net_turnover)}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-gray-300">信号</span>
            <span className="font-medium">{summary.label}</span>
          </div>
          {/* 小三角 */}
          <div className="absolute top-full left-1/2 -translate-x-1/2 border-4 border-transparent border-t-gray-800" />
        </div>
      )}
    </span>
  );
}
