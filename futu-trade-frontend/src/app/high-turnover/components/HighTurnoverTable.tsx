// 活跃个股表格组件

"use client";

import Link from "next/link";
import type { HighTurnoverStock } from "@/types/stock";
import { formatPercent, formatPrice } from "@/lib/utils";
import TradeDirectionBadge from "./TradeDirectionBadge";
import BuyRatioCell from "./BuyRatioCell";
import BigOrderPctCell from "./BigOrderPctCell";
import { Tooltip } from "@/components/common/Tooltip";

/** 排序方向 */
export type SortDirection = "asc" | "desc";

/** 可排序的字段 */
export type SortField =
  | "rank"
  | "turnover_rate"
  | "change_rate"
  | "last_price"
  | "volume"
  | "turnover"
  | "volume_ratio"
  | "amplitude"
  | "score"
  | "buy_sell_ratio"
  | "big_order_pct";

interface HighTurnoverTableProps {
  /** 股票数据列表 */
  stocks: HighTurnoverStock[];
  /** 当前排序字段 */
  sortField: SortField;
  /** 当前排序方向 */
  sortDirection: SortDirection;
  /** 排序变更回调 */
  onSortChange: (field: SortField) => void;
  /** 成交分析数据是否加载中 */
  tickerLoading?: boolean;
  /** 行点击回调 */
  onRowClick?: (stock: HighTurnoverStock) => void;
}

/** 换手率颜色渐变规则 */
function getTurnoverColorClass(rate: number): string {
  if (rate >= 10) return "text-red-700 bg-red-100";
  if (rate >= 5) return "text-red-600 bg-red-50";
  if (rate >= 2) return "text-orange-600 bg-orange-50";
  if (rate >= 1) return "text-yellow-600 bg-yellow-50";
  return "text-gray-600 bg-gray-50";
}

/** 格式化成交量（万/亿） */
function formatVolumeZh(volume: number): string {
  if (volume >= 1_0000_0000) return (volume / 1_0000_0000).toFixed(2) + "亿";
  if (volume >= 1_0000) return (volume / 1_0000).toFixed(1) + "万";
  return volume.toLocaleString("zh-CN");
}

/** 格式化成交额（万/亿） */
function formatTurnoverZh(turnover: number): string {
  if (turnover >= 1_0000_0000) return (turnover / 1_0000_0000).toFixed(2) + "亿";
  if (turnover >= 1_0000) return (turnover / 1_0000).toFixed(1) + "万";
  return turnover.toFixed(2);
}

/** 表头列定义 */
const COLUMNS: { key: SortField | "name" | "plates" | "bull_pct" | "signal_label"; label: string; sortable: boolean; align: string; tooltip?: string }[] = [
  { key: "rank", label: "排名", sortable: true, align: "text-center" },
  { key: "name", label: "股票名称/代码", sortable: false, align: "text-left" },
  { key: "turnover_rate", label: "换手率", sortable: true, align: "text-right" },
  { key: "change_rate", label: "涨跌幅", sortable: true, align: "text-right" },
  { key: "amplitude", label: "振幅", sortable: true, align: "text-right" },
  { key: "last_price", label: "现价", sortable: true, align: "text-right" },
  { key: "volume", label: "成交量", sortable: true, align: "text-right" },
  { key: "turnover", label: "成交额", sortable: true, align: "text-right" },
  { key: "score", label: "成交方向", sortable: true, align: "text-center", tooltip: "根据逐笔成交分析，判断主动买卖力量对比" },
  { key: "buy_sell_ratio", label: "力量比", sortable: true, align: "text-right", tooltip: "主动买入金额 / 主动卖出金额" },
  { key: "big_order_pct", label: "大单占比", sortable: true, align: "text-right", tooltip: "单笔成交额 > 10万元的成交占比" },
  { key: "bull_pct", label: "多空占比", sortable: false, align: "text-center", tooltip: "基于主动买卖量计算的多空力量对比" },
  { key: "signal_label", label: "信号", sortable: true, align: "text-center", tooltip: "综合多空分析信号" },
  { key: "plates", label: "所属板块", sortable: false, align: "text-left" },
  { key: "volume_ratio", label: "量比", sortable: true, align: "text-right" },
];

export default function HighTurnoverTable({
  stocks,
  sortField,
  sortDirection,
  onSortChange,
  tickerLoading = false,
  onRowClick,
}: HighTurnoverTableProps) {
  /** 渲染排序图标 */
  const renderSortIcon = (field: string) => {
    if (field !== sortField) {
      return <i className="fas fa-sort text-gray-300 ml-1" />;
    }
    return sortDirection === "asc" ? (
      <i className="fas fa-sort-up text-blue-600 ml-1" />
    ) : (
      <i className="fas fa-sort-down text-blue-600 ml-1" />
    );
  };

  if (stocks.length === 0) {
    return (
      <div className="text-center py-12 text-gray-500">
        <i className="fas fa-inbox text-4xl mb-4" />
        <p>暂无活跃个股数据</p>
      </div>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="min-w-full divide-y divide-gray-200">
        <thead className="bg-gray-50">
          <tr>
            {COLUMNS.map((col) => (
              <th
                key={col.key}
                className={`px-4 py-3 text-xs font-medium text-gray-500 uppercase ${col.align} ${col.sortable ? "cursor-pointer hover:bg-gray-100 select-none" : ""
                  }`}
                onClick={() => col.sortable && onSortChange(col.key as SortField)}
              >
                {col.tooltip ? (
                  <Tooltip content={col.tooltip} side="top">
                    <span className="inline-flex items-center cursor-help">
                      {col.label}
                      {col.sortable && renderSortIcon(col.key)}
                    </span>
                  </Tooltip>
                ) : (
                  <span className="inline-flex items-center">
                    {col.label}
                    {col.sortable && renderSortIcon(col.key)}
                  </span>
                )}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="bg-white divide-y divide-gray-200">
          {stocks.map((stock) => {
            const changeColor = stock.change_rate >= 0 ? "text-red-600" : "text-green-600";
            const changePrefix = stock.change_rate >= 0 ? "+" : "";

            return (
              <tr key={stock.code} className={`hover:bg-gray-50 ${onRowClick ? "cursor-pointer" : ""}`} onClick={() => onRowClick?.(stock)}>
                {/* 排名 */}
                <td className="px-4 py-3 text-sm text-center text-gray-500 font-medium">
                  {stock.rank}
                </td>

                {/* 股票名称/代码 */}
                <td className="px-4 py-3 text-sm">
                  <div className="font-medium text-gray-900 flex items-center gap-1">
                    {stock.name}
                    {stock.is_position && (
                      <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium bg-purple-100 text-purple-700" title="持仓股票">
                        持仓
                      </span>
                    )}
                  </div>
                  <div className="text-xs text-gray-500">{stock.code}</div>
                </td>

                {/* 换手率（颜色渐变高亮） */}
                <td className="px-4 py-3 text-sm text-right">
                  <span
                    className={`inline-block px-2 py-0.5 rounded font-semibold ${getTurnoverColorClass(stock.turnover_rate)}`}
                  >
                    {formatPercent(stock.turnover_rate)}
                  </span>
                </td>

                {/* 涨跌幅（红涨绿跌） */}
                <td className={`px-4 py-3 text-sm text-right font-medium ${changeColor}`}>
                  {changePrefix}{formatPercent(stock.change_rate)}
                </td>

                {/* 振幅 */}
                <td className="px-4 py-3 text-sm text-right text-gray-900">
                  {stock.amplitude > 0 ? formatPercent(stock.amplitude) : "-"}
                </td>

                {/* 现价 */}
                <td className="px-4 py-3 text-sm text-right text-gray-900">
                  {formatPrice(stock.last_price)}
                </td>

                {/* 成交量 */}
                <td className="px-4 py-3 text-sm text-right text-gray-900">
                  {formatVolumeZh(stock.volume)}
                </td>

                {/* 成交额 */}
                <td className="px-4 py-3 text-sm text-right text-gray-900">
                  {formatTurnoverZh(stock.turnover)}
                </td>

                {/* 成交方向 */}
                <td className="px-4 py-3 text-sm text-center">
                  <TradeDirectionBadge summary={stock.ticker_summary} loading={tickerLoading} />
                </td>

                {/* 力量比 */}
                <td className="px-4 py-3 text-sm text-right">
                  <BuyRatioCell summary={stock.ticker_summary} loading={tickerLoading} />
                </td>

                {/* 大单占比 */}
                <td className="px-4 py-3 text-sm text-right">
                  <BigOrderPctCell summary={stock.ticker_summary} loading={tickerLoading} />
                </td>

                {/* 多空占比 */}
                <td className="px-3 py-3 text-sm text-center">
                  {stock.ticker_summary ? (() => {
                    const ratio = stock.ticker_summary.buy_sell_ratio;
                    const bullPct = ratio >= 999 ? 99 : Math.round((ratio / (1 + ratio)) * 100);
                    const bearPct = 100 - bullPct;
                    const barColor = bullPct >= 60 ? "bg-green-500" : bullPct <= 40 ? "bg-red-500" : "bg-yellow-500";
                    const textColor = bullPct >= 60 ? "text-green-600" : bullPct <= 40 ? "text-red-600" : "text-gray-600";
                    return (
                      <div className="flex flex-col items-center gap-0.5">
                        <div className="flex h-[5px] w-full max-w-[60px] overflow-hidden rounded-full bg-gray-200">
                          <div className={barColor} style={{ width: `${bullPct}%` }} />
                          <div className="bg-red-300" style={{ width: `${bearPct}%` }} />
                        </div>
                        <span className={`text-[10px] font-medium ${textColor}`}>
                          {bullPct >= 60 ? `多${bullPct}%` : bullPct <= 40 ? `空${bearPct}%` : `${bullPct}/${bearPct}`}
                        </span>
                      </div>
                    );
                  })() : <span className="text-gray-300 text-xs">-</span>}
                </td>

                {/* 信号 */}
                <td className="px-3 py-3 text-sm text-center">
                  {stock.ticker_summary ? (() => {
                    const s = stock.ticker_summary;
                    const colorMap: Record<string, string> = {
                      bullish: "bg-green-100 text-green-700",
                      slightly_bullish: "bg-green-50 text-green-600",
                      neutral: "bg-gray-100 text-gray-600",
                      slightly_bearish: "bg-red-50 text-red-600",
                      bearish: "bg-red-100 text-red-700",
                    };
                    const cls = colorMap[s.signal] || colorMap.neutral;
                    return (
                      <span className={`inline-block px-1.5 py-0.5 rounded text-[10px] font-medium ${cls}`}>
                        {s.label}
                      </span>
                    );
                  })() : <span className="text-gray-300 text-xs">-</span>}
                </td>

                {/* 所属板块 */}
                <td className="px-4 py-3 text-sm">
                  <div className="flex flex-wrap gap-1">
                    {stock.plates.length > 0 ? (
                      stock.plates.map((plate) => (
                        <Link
                          key={plate.plate_code}
                          href={`/plate/${plate.plate_code}`}
                          className="inline-block px-2 py-0.5 bg-blue-50 text-blue-600 rounded text-xs hover:bg-blue-100 hover:text-blue-800 transition-colors"
                        >
                          {plate.plate_name}
                        </Link>
                      ))
                    ) : (
                      <span className="text-gray-400 text-xs">-</span>
                    )}
                  </div>
                </td>

                {/* 量比 */}
                <td className="px-4 py-3 text-sm text-right text-gray-900">
                  {stock.volume_ratio > 0 ? stock.volume_ratio.toFixed(2) : "-"}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
