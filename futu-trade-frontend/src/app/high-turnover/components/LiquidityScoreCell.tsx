// 流动性评分单元格组件

"use client";

import { Tooltip } from "@/components/common/Tooltip";

interface LiquidityScoreCellProps {
  score?: number;
  level?: string;
  isAnomaly?: boolean;
  klineDataMissing?: boolean;
}

/** 流动性等级颜色映射 */
function getLevelColorClass(level: string): string {
  switch (level) {
    case "A":
      return "text-green-700 bg-green-100";
    case "B":
      return "text-blue-700 bg-blue-100";
    case "C":
      return "text-yellow-700 bg-yellow-100";
    case "D":
      return "text-red-700 bg-red-100";
    default:
      return "text-foreground bg-muted";
  }
}

export default function LiquidityScoreCell({
  score = 50,
  level = "B",
  isAnomaly = false,
  klineDataMissing = false,
}: LiquidityScoreCellProps) {
  // K线数据不足时显示"评测中"
  if (klineDataMissing) {
    return (
      <Tooltip content="历史K线数据不足，正在后台补充下载，完成后将显示完整评分">
        <div className="flex items-center gap-1.5">
          <span className="inline-flex items-center px-2 py-1 rounded text-xs font-medium text-amber-700 bg-amber-50 border border-amber-200">
            <i className="fas fa-spinner fa-spin mr-1 text-[10px]" />
            评测中
          </span>
        </div>
      </Tooltip>
    );
  }

  const colorClass = getLevelColorClass(level);

  return (
    <div className="flex items-center gap-2">
      <Tooltip content={`流动性评分: ${score.toFixed(1)}`}>
        <span
          className={`inline-flex items-center px-2 py-1 rounded text-xs font-medium ${colorClass}`}
        >
          {level}级
        </span>
      </Tooltip>
      <span className="text-sm text-foreground">{score.toFixed(1)}</span>
      {isAnomaly && (
        <Tooltip content="检测到异常成交量放大">
          <i className="fas fa-exclamation-triangle text-orange-500 text-xs" />
        </Tooltip>
      )}
    </div>
  );
}
