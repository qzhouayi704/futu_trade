// 活跃个股筛选栏组件

"use client";

import { Button } from "@/components/common";

interface HighTurnoverFiltersProps {
  /** 当前选中的市场筛选值 */
  marketFilter: string;
  /** 当前搜索关键词 */
  searchKeyword: string;
  /** 当前选中的成交方向筛选值 */
  directionFilter: "all" | "bullish" | "bearish" | "neutral";
  /** 市场筛选变更回调 */
  onMarketChange: (market: string) => void;
  /** 搜索关键词变更回调 */
  onSearchChange: (keyword: string) => void;
  /** 成交方向筛选变更回调 */
  onDirectionChange: (direction: "all" | "bullish" | "bearish" | "neutral") => void;
}


const MARKET_OPTIONS = [
  { value: "all", label: "全部" },
  { value: "HK", label: "港股" },
  { value: "US", label: "美股" },
] as const;

const DIRECTION_OPTIONS = [
  { value: "all", label: "全部" },
  { value: "bullish", label: "偏多" },
  { value: "bearish", label: "偏空" },
  { value: "neutral", label: "中性" },
] as const;

export default function HighTurnoverFilters({
  marketFilter,
  searchKeyword,
  directionFilter,
  onMarketChange,
  onSearchChange,
  onDirectionChange,
}: HighTurnoverFiltersProps) {
  return (
    <div className="flex flex-wrap items-center gap-4">
      {/* 市场筛选 */}
      <div className="flex items-center gap-2">
        <span className="text-sm font-medium text-gray-700">市场：</span>
        <div className="flex gap-2">
          {MARKET_OPTIONS.map((option) => (
            <Button
              key={option.value}
              size="sm"
              variant={marketFilter === option.value ? "primary" : "secondary"}
              onClick={() => onMarketChange(option.value)}
            >
              {option.label}
            </Button>
          ))}
        </div>
      </div>

      {/* 成交方向筛选 */}
      <div className="flex items-center gap-2">
        <span className="text-sm font-medium text-gray-700">方向：</span>
        <div className="flex gap-2">
          {DIRECTION_OPTIONS.map((option) => (
            <Button
              key={option.value}
              size="sm"
              variant={directionFilter === option.value ? "primary" : "secondary"}
              onClick={() => onDirectionChange(option.value)}
            >
              {option.label}
            </Button>
          ))}
        </div>
      </div>

      {/* 搜索输入框 */}
      <div className="flex items-center gap-2 ml-auto">
        <div className="relative">
          <i className="fas fa-search absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 text-sm" />
          <input
            type="text"
            placeholder="搜索代码或名称..."
            value={searchKeyword}
            onChange={(e) => onSearchChange(e.target.value)}
            className="pl-9 pr-4 py-1.5 text-sm border border-gray-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500 w-56"
          />
          {searchKeyword && (
            <button
              onClick={() => onSearchChange("")}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
            >
              <i className="fas fa-times text-xs" />
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
