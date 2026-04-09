// 大单占比单元格组件
// 根据 big_order_pct 值显示颜色渐变，支持骨架屏

import type { TickerSummary } from "@/types/stock";
import { formatPercent } from "@/lib/utils";
import { Tooltip } from "@/components/common/Tooltip";

interface BigOrderPctCellProps {
  /** 成交分析摘要，null 表示数据不可用 */
  summary: TickerSummary | null;
  /** 是否正在加载 */
  loading?: boolean;
}

/** 根据大单占比返回对应颜色 class */
function getPctColor(pct: number): string {
  if (pct >= 30) return "text-red-600 font-semibold";
  if (pct >= 15) return "text-orange-600";
  if (pct > 0) return "text-gray-700";
  return "text-gray-400";
}

export default function BigOrderPctCell({ summary, loading }: BigOrderPctCellProps) {
  if (loading) {
    return (
      <span className="inline-block w-10 h-4 bg-gray-200 rounded animate-pulse" />
    );
  }

  if (!summary || summary.big_order_pct === undefined) {
    return <span className="text-gray-400">-</span>;
  }

  const color = getPctColor(summary.big_order_pct);

  return (
    <Tooltip
      content={
        <div className="space-y-1">
          <div className="font-medium">大单占比：单笔成交额 &gt; 10万元的成交占比</div>
          <div className="text-gray-300 space-y-0.5">
            <div>• ≥30% 表示机构资金活跃</div>
            <div>• ≥15% 表示有一定关注度</div>
            <div>• &lt;15% 表示散户为主</div>
          </div>
        </div>
      }
      side="top"
    >
      <span className={`cursor-help ${color}`}>
        {formatPercent(summary.big_order_pct)}
      </span>
    </Tooltip>
  );
}
