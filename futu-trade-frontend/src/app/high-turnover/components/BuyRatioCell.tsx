// 力量比单元格组件
// 根据 buy_sell_ratio 值显示红/绿/灰色文字，支持骨架屏

import type { TickerSummary } from "@/types/stock";
import { Tooltip } from "@/components/common/Tooltip";

interface BuyRatioCellProps {
  /** 成交分析摘要，null 表示数据不可用 */
  summary: TickerSummary | null;
  /** 是否正在加载 */
  loading?: boolean;
}

/** 根据力量比返回对应颜色 class */
export function getRatioColor(ratio: number): string {
  if (ratio > 1.0) return "text-red-600";
  if (ratio < 1.0) return "text-green-600";
  return "text-gray-500";
}

export default function BuyRatioCell({ summary, loading }: BuyRatioCellProps) {
  // 骨架屏
  if (loading) {
    return (
      <span className="inline-block w-8 h-4 bg-gray-200 rounded animate-pulse" />
    );
  }

  // 数据不可用
  if (!summary) {
    return <span className="text-gray-400">-</span>;
  }

  const color = getRatioColor(summary.buy_sell_ratio);

  return (
    <Tooltip
      content={
        <div className="space-y-1">
          <div className="font-medium">力量比 = 主动买入金额 / 主动卖出金额</div>
          <div className="text-gray-300">
            {summary.buy_sell_ratio > 1.0 && "• > 1.0 表示买方占优"}
            {summary.buy_sell_ratio < 1.0 && "• < 1.0 表示卖方占优"}
            {summary.buy_sell_ratio === 1.0 && "• = 1.0 表示多空平衡"}
          </div>
        </div>
      }
      side="top"
    >
      <span className={`font-medium cursor-help ${color}`}>
        {summary.buy_sell_ratio.toFixed(2)}
      </span>
    </Tooltip>
  );
}
