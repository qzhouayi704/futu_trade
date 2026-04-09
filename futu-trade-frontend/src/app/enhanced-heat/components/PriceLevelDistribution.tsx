// 价位成交分布 - 双向柱状图展示每个价位的买入/卖出量分布

"use client";

import type {
  PriceLevelDistributionData,
  PriceLevelItem,
} from "@/types/enhanced-heat";

// ==================== 工具函数 ====================

function formatVolume(v: number): string {
  if (v >= 100000000) return `${(v / 100000000).toFixed(2)}亿`;
  if (v >= 10000) return `${(v / 10000).toFixed(1)}万`;
  return v.toLocaleString();
}

function formatPrice(price: number): string {
  return price.toFixed(price >= 100 ? 2 : 3);
}

/** 计算柱状图最大基准值 */
function getMaxVolume(levels: PriceLevelItem[]): number {
  let max = 0;
  for (const level of levels) {
    if (level.buy_volume > max) max = level.buy_volume;
    if (level.sell_volume > max) max = level.sell_volume;
  }
  return max || 1; // 避免除以零
}

// ==================== 子组件 ====================

interface PriceLevelRowProps {
  level: PriceLevelItem;
  maxVolume: number;
  isCurrentPrice: boolean;
}

/** 单个价位行 */
function PriceLevelRow({ level, maxVolume, isCurrentPrice }: PriceLevelRowProps) {
  const buyPct = (level.buy_volume / maxVolume) * 100;
  const sellPct = (level.sell_volume / maxVolume) * 100;

  return (
    <div className={`flex items-center gap-1 py-0.5 text-xs ${isCurrentPrice ? "bg-blue-50" : ""}`}>
      {/* 左侧：卖出量柱（向左延伸） */}
      <div className="flex-1 flex items-center justify-end gap-1">
        <span className="text-green-600 shrink-0 w-12 text-right font-mono text-[11px]">
          {level.sell_volume > 0 ? formatVolume(level.sell_volume) : ""}
        </span>
        <div className="w-24 h-4 flex justify-end">
          <div
            className="h-full bg-green-400 rounded-l transition-all duration-300"
            style={{ width: `${sellPct}%` }}
          />
        </div>
      </div>

      {/* 中间：价格 */}
      <span className={`w-16 text-center font-mono shrink-0 ${
        isCurrentPrice ? "text-blue-600 font-bold" : "text-gray-700"
      }`}>
        {formatPrice(level.price)}
      </span>

      {/* 右侧：买入量柱（向右延伸） */}
      <div className="flex-1 flex items-center gap-1">
        <div className="w-24 h-4 flex justify-start">
          <div
            className="h-full bg-red-400 rounded-r transition-all duration-300"
            style={{ width: `${buyPct}%` }}
          />
        </div>
        <span className="text-red-600 shrink-0 w-12 text-left font-mono text-[11px]">
          {level.buy_volume > 0 ? formatVolume(level.buy_volume) : ""}
        </span>
      </div>
    </div>
  );
}

/** 当前价分隔线 */
function CurrentPriceDivider() {
  return (
    <div className="flex items-center gap-2 py-0.5">
      <div className="flex-1 border-t border-dashed border-blue-400" />
      <span className="text-[10px] text-blue-500 shrink-0">当前价</span>
      <div className="flex-1 border-t border-dashed border-blue-400" />
    </div>
  );
}

interface SummaryRowProps {
  levels: PriceLevelItem[];
}

/** 底部汇总行 */
function SummaryRow({ levels }: SummaryRowProps) {
  const totalBuy = levels.reduce((sum, l) => sum + l.buy_volume, 0);
  const totalSell = levels.reduce((sum, l) => sum + l.sell_volume, 0);
  const ratio = totalSell === 0 ? "∞" : (totalBuy / totalSell).toFixed(2);

  return (
    <div className="flex items-center justify-between text-xs border-t border-gray-200 pt-2 mt-2 px-1">
      <span className="text-gray-500">
        买入: <span className="text-red-600 font-medium">{formatVolume(totalBuy)}</span>
      </span>
      <span className="text-gray-500">
        卖出: <span className="text-green-600 font-medium">{formatVolume(totalSell)}</span>
      </span>
      <span className="text-gray-500">
        买卖比: <span className="text-gray-800 font-medium">{ratio}</span>
      </span>
    </div>
  );
}

// ==================== 主组件 ====================

interface PriceLevelDistributionProps {
  data: PriceLevelDistributionData | null;
  loading?: boolean;
}

export function PriceLevelDistribution({ data, loading }: PriceLevelDistributionProps) {
  // 空数据状态
  if (!data || data.levels.length === 0) {
    if (loading) {
      return (
        <div>
          <div className="text-xs text-gray-500 mb-2 font-medium">价位成交分布</div>
          <div className="text-sm text-gray-400 text-center py-4">加载中...</div>
        </div>
      );
    }
    return (
      <div>
        <div className="text-xs text-gray-500 mb-2 font-medium">价位成交分布</div>
        <div className="text-sm text-gray-400 text-center py-4">暂无价位分布数据</div>
      </div>
    );
  }

  const maxVolume = getMaxVolume(data.levels);
  const currentPrice = data.current_price;

  // 找到当前价应该插入分隔线的位置
  // levels 按价格从高到低排序，分隔线插在第一个 <= currentPrice 的价位之前
  let dividerIndex = -1;
  for (let i = 0; i < data.levels.length; i++) {
    if (data.levels[i].price <= currentPrice) {
      dividerIndex = i;
      break;
    }
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-2">
        <div className="text-xs text-gray-500 font-medium">价位成交分布</div>
        <div className="text-[10px] text-gray-400">
          共 {data.level_count} 个价位 · 总量 {formatVolume(data.total_volume)}
        </div>
      </div>

      {/* 表头 */}
      <div className="flex items-center gap-1 text-[10px] text-gray-400 mb-1 px-1">
        <div className="flex-1 text-right">← 卖出量</div>
        <span className="w-16 text-center">价格</span>
        <div className="flex-1 text-left">买入量 →</div>
      </div>

      {/* 价位列表（限制高度，超出滚动） */}
      <div className="space-y-0 max-h-64 overflow-y-auto scrollbar-thin">
        {data.levels.map((level, i) => {
          const isCurrentPrice = level.price === currentPrice;
          const showDivider = dividerIndex === i && !isCurrentPrice;

          return (
            <div key={level.price}>
              {showDivider && <CurrentPriceDivider />}
              <PriceLevelRow
                level={level}
                maxVolume={maxVolume}
                isCurrentPrice={isCurrentPrice}
              />
            </div>
          );
        })}
        {/* 如果所有价位都高于当前价，分隔线在最后 */}
        {dividerIndex === -1 && <CurrentPriceDivider />}
      </div>

      {/* 汇总行 */}
      <SummaryRow levels={data.levels} />
    </div>
  );
}
