// 盘口10档深度组件 - 展示买卖盘挂单量、失衡度、支撑阻力位

"use client";

import type { OrderBookResponse, OrderBookLevel } from "@/types/enhanced-heat";

interface OrderBookDepthProps {
  orderBook: OrderBookResponse | null;
  loading: boolean;
}

/** 格式化挂单量 */
function formatVolume(vol: number | undefined | null): string {
  if (vol == null) return "-";
  if (vol >= 1_0000) return (vol / 1_0000).toFixed(1) + "万";
  return vol.toLocaleString();
}


/** 格式化价差 */
function formatSpread(spread: number | undefined | null, spreadPct: number | undefined | null): string {
  if (spread == null || spreadPct == null) return "-";
  return `${spread.toFixed(3)} (${(spreadPct * 100).toFixed(2)}%)`;
}


/** 失衡度颜色 */
function getImbalanceColor(imbalance: number): string {
  if (imbalance > 0.1) return "text-red-400";
  if (imbalance < -0.1) return "text-green-400";
  return "text-gray-400";
}

/** 失衡度条 - 红绿对比 */
function ImbalanceBar({ imbalance }: { imbalance: number }) {
  // imbalance 范围 [-1, 1]，映射到 [0%, 100%]，0 对应 50%
  const buyPct = ((imbalance + 1) / 2) * 100;

  return (
    <div className="flex h-3 rounded-full overflow-hidden bg-gray-700">
      <div className="bg-red-500/80 transition-all" style={{ width: `${buyPct}%` }} />
      <div className="bg-green-500/80 transition-all" style={{ width: `${100 - buyPct}%` }} />
    </div>
  );
}

/** 判断是否为支撑位或阻力位 */
function isHighlighted(
  level: OrderBookLevel,
  support: OrderBookResponse["support"],
  resistance: OrderBookResponse["resistance"],
  side: "bid" | "ask"
): boolean {
  if (side === "bid" && support && level.price === support.price && level.volume === support.volume) {
    return true;
  }
  if (side === "ask" && resistance && level.price === resistance.price && level.volume === resistance.volume) {
    return true;
  }
  return false;
}

/** 骨架屏 */
function Skeleton() {
  return (
    <div className="space-y-3 animate-pulse">
      <div className="grid grid-cols-3 gap-2">
        {[1, 2, 3].map((i) => (
          <div key={i} className="h-14 bg-gray-700/50 rounded" />
        ))}
      </div>
      <div className="h-3 bg-gray-700/50 rounded" />
      <div className="space-y-1">
        {Array.from({ length: 10 }, (_, i) => (
          <div key={`ask-${i}`} className="h-7 bg-gray-700/50 rounded" />
        ))}
      </div>
      <div className="h-px bg-gray-600" />
      <div className="space-y-1">
        {Array.from({ length: 10 }, (_, i) => (
          <div key={`bid-${i}`} className="h-7 bg-gray-700/50 rounded" />
        ))}
      </div>
    </div>
  );
}

/** 汇总统计区域 */
function SummarySection({ orderBook }: { orderBook: OrderBookResponse }) {
  const { bid_total_volume = 0, ask_total_volume = 0, imbalance = 0, spread = 0, spread_pct = 0 } = orderBook;

  return (
    <div className="space-y-3">
      {/* 买卖盘总量 + 价差 */}
      <div className="grid grid-cols-3 gap-2">
        <div className="bg-gray-800/50 rounded p-2 text-center">
          <div className="text-[10px] text-gray-500">买盘总量</div>
          <div className="text-sm font-medium text-red-400">{formatVolume(bid_total_volume)}</div>
        </div>
        <div className="bg-gray-800/50 rounded p-2 text-center">
          <div className="text-[10px] text-gray-500">卖盘总量</div>
          <div className="text-sm font-medium text-green-400">{formatVolume(ask_total_volume)}</div>
        </div>
        <div className="bg-gray-800/50 rounded p-2 text-center">
          <div className="text-[10px] text-gray-500">价差</div>
          <div className="text-sm font-medium text-gray-300">{formatSpread(spread, spread_pct)}</div>
        </div>
      </div>

      {/* 失衡度 */}
      <div className="bg-gray-800/50 rounded p-2">
        <div className="flex items-center justify-between text-xs mb-1">
          <span className="text-gray-400">买卖失衡度</span>
          <span className={`font-medium ${getImbalanceColor(imbalance)}`}>
            {imbalance > 0 ? "+" : ""}{(imbalance * 100).toFixed(1)}%
          </span>
        </div>
        <ImbalanceBar imbalance={imbalance} />
        <div className="flex justify-between text-[10px] text-gray-500 mt-0.5">
          <span>卖方主导</span>
          <span>买方主导</span>
        </div>
      </div>
    </div>
  );
}

/** 单档盘口行 */
function LevelRow({
  level,
  maxVolume,
  side,
  highlighted,
}: {
  level: OrderBookLevel;
  maxVolume: number;
  side: "bid" | "ask";
  highlighted: boolean;
}) {
  const barPct = maxVolume > 0 ? (level.volume / maxVolume) * 100 : 0;
  const barColor = side === "bid" ? "bg-red-500/30" : "bg-green-500/30";
  const priceColor = side === "bid" ? "text-red-400" : "text-green-400";
  const borderClass = highlighted ? "border border-yellow-500/60 rounded" : "";

  return (
    <div className={`relative flex items-center h-7 px-2 text-xs ${borderClass}`}>
      {/* 背景柱状图 */}
      <div
        className={`absolute inset-y-0 ${side === "bid" ? "right-0" : "left-0"} ${barColor} transition-all`}
        style={{ width: `${barPct}%` }}
      />
      {/* 数据 */}
      <div className="relative z-10 flex items-center w-full">
        <span className={`w-20 font-mono ${priceColor}`}>{level.price.toFixed(3)}</span>
        <span className="flex-1 text-right text-gray-300 font-mono">{formatVolume(level.volume)}</span>
        <span className="w-12 text-right text-gray-500 font-mono">{level.order_count}</span>
      </div>
      {/* 支撑/阻力标记 */}
      {highlighted && (
        <span className="absolute right-1 top-0.5 text-[9px] text-yellow-400">
          {side === "bid" ? "支撑" : "阻力"}
        </span>
      )}
    </div>
  );
}

/** 盘口档位列表 */
function OrderLevelsSection({ orderBook }: { orderBook: OrderBookResponse }) {
  const { bid_levels, ask_levels, support, resistance } = orderBook;

  // 计算所有档位中的最大挂单量，用于柱状图比例
  const allVolumes = [...bid_levels, ...ask_levels].map((l) => l.volume);
  const maxVolume = Math.max(...allVolumes, 1);

  // 卖盘：卖10到卖1（反转显示，高价在上）
  const askReversed = [...ask_levels].reverse();

  return (
    <div>
      {/* 表头 */}
      <div className="flex items-center px-2 text-[10px] text-gray-500 mb-1">
        <span className="w-20">价格</span>
        <span className="flex-1 text-right">挂单量</span>
        <span className="w-12 text-right">笔数</span>
      </div>

      {/* 卖盘（卖10→卖1，绿色） */}
      <div className="space-y-px">
        {askReversed.map((level, idx) => (
          <LevelRow
            key={`ask-${idx}`}
            level={level}
            maxVolume={maxVolume}
            side="ask"
            highlighted={isHighlighted(level, support, resistance, "ask")}
          />
        ))}
      </div>

      {/* 分隔线 */}
      <div className="my-1 border-t border-dashed border-gray-600" />

      {/* 买盘（买1→买10，红色） */}
      <div className="space-y-px">
        {bid_levels.map((level, idx) => (
          <LevelRow
            key={`bid-${idx}`}
            level={level}
            maxVolume={maxVolume}
            side="bid"
            highlighted={isHighlighted(level, support, resistance, "bid")}
          />
        ))}
      </div>
    </div>
  );
}

/** 盘口10档深度组件 */
export default function OrderBookDepth({ orderBook, loading }: OrderBookDepthProps) {
  if (loading) {
    return <Skeleton />;
  }

  if (!orderBook) {
    return (
      <div className="text-center text-gray-500 text-sm py-8">
        暂无盘口数据
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <SummarySection orderBook={orderBook} />
      <OrderLevelsSection orderBook={orderBook} />
    </div>
  );
}
