// 盘口深度分析面板 - 买卖十档可视化 + 5维度涨跌动力分析

"use client";

import { useState, useEffect, useCallback } from "react";
import type {
  OrderBookAnalysisData,
  OrderBookLevel,
  DimensionSignal,
  SignalType,
} from "@/types/enhanced-heat";
import { getOrderBookAnalysis } from "@/lib/api/enhanced-heat";

// ==================== 信号样式映射 ====================

const SIGNAL_STYLES: Record<SignalType, { bg: string; text: string; label: string }> = {
  bullish: { bg: "bg-red-100 border-red-200", text: "text-red-700", label: "看涨" },
  slightly_bullish: { bg: "bg-red-50 border-red-100", text: "text-red-600", label: "偏多" },
  neutral: { bg: "bg-gray-100 border-gray-200", text: "text-gray-600", label: "中性" },
  slightly_bearish: { bg: "bg-green-50 border-green-100", text: "text-green-600", label: "偏空" },
  bearish: { bg: "bg-green-100 border-green-200", text: "text-green-700", label: "看跌" },
};

function formatVolume(v: number): string {
  if (v >= 10000) return `${(v / 10000).toFixed(1)}万`;
  return v.toLocaleString();
}

// ==================== 子组件 ====================

/** 综合判断标签 */
function SummaryBadge({ data }: { data: OrderBookAnalysisData }) {
  const style = SIGNAL_STYLES[data.signal] || SIGNAL_STYLES.neutral;
  return (
    <div className={`rounded-lg border p-3 mb-4 ${style.bg}`}>
      <div className="flex items-center justify-between mb-1">
        <span className={`text-lg font-bold ${style.text}`}>{data.label}</span>
        <span className={`text-sm font-medium ${style.text}`}>
          评分: {data.total_score > 0 ? "+" : ""}{data.total_score}
        </span>
      </div>
      <p className="text-sm text-gray-700">{data.summary}</p>
    </div>
  );
}

/** 单档挂单行 */
function LevelRow({
  level, maxVol, side, isHighlight, label,
}: {
  level: OrderBookLevel;
  maxVol: number;
  side: "bid" | "ask";
  isHighlight: boolean;
  label: string;
}) {
  const pct = maxVol > 0 ? (level.volume / maxVol) * 100 : 0;
  const barColor = side === "bid" ? "bg-red-300" : "bg-green-300";
  const priceColor = side === "bid" ? "text-red-600" : "text-green-600";

  return (
    <div className={`flex items-center gap-2 py-0.5 px-1 rounded ${isHighlight ? "bg-yellow-50 ring-1 ring-yellow-300" : ""}`}>
      <span className="w-8 text-xs text-gray-400 text-right shrink-0">{label}</span>
      <span className={`w-16 text-xs font-mono text-right shrink-0 ${priceColor}`}>
        {level.price.toFixed(2)}
      </span>
      <div className="flex-1 h-4 bg-gray-100 rounded overflow-hidden">
        <div
          className={`h-full ${barColor} transition-all duration-300 rounded`}
          style={{ width: `${Math.min(pct, 100)}%` }}
        />
      </div>
      <span className="w-16 text-xs text-gray-600 text-right shrink-0">
        {formatVolume(level.volume)}
      </span>
      {isHighlight && (
        <span className="text-xs text-yellow-600 shrink-0">
          {side === "bid" ? "支撑" : "阻力"}
        </span>
      )}
    </div>
  );
}

/** 买卖十档表 */
function OrderBookTable({ data }: { data: OrderBookAnalysisData }) {
  const ob = data.order_book;
  const allVols = [...ob.ask_levels, ...ob.bid_levels].map((l) => l.volume);
  const maxVol = Math.max(...allVols, 1);

  const supPrice = ob.support?.price;
  const resPrice = ob.resistance?.price;

  // 卖盘从高到低（反转后卖10在上）
  const askReversed = [...ob.ask_levels].reverse();

  return (
    <div className="mb-4">
      <div className="text-xs text-gray-500 mb-1 font-medium">买卖十档</div>
      <div className="space-y-0.5">
        {askReversed.map((level, i) => (
          <LevelRow
            key={`ask-${i}`}
            level={level}
            maxVol={maxVol}
            side="ask"
            isHighlight={resPrice !== undefined && level.price === resPrice}
            label={`卖${ob.ask_levels.length - i}`}
          />
        ))}

        {/* 价差分隔行 */}
        <div className="flex items-center gap-2 py-1 px-1">
          <div className="flex-1 border-t border-dashed border-gray-300" />
          <span className="text-xs text-gray-400 shrink-0">
            价差 {ob.spread.toFixed(2)} ({ob.spread_pct.toFixed(3)}%)
          </span>
          <div className="flex-1 border-t border-dashed border-gray-300" />
        </div>

        {ob.bid_levels.map((level, i) => (
          <LevelRow
            key={`bid-${i}`}
            level={level}
            maxVol={maxVol}
            side="bid"
            isHighlight={supPrice !== undefined && level.price === supPrice}
            label={`买${i + 1}`}
          />
        ))}
      </div>

      {/* 汇总行 */}
      <div className="flex justify-between text-xs text-gray-500 mt-2 px-1">
        <span>买盘总量: <span className="text-red-600 font-medium">{formatVolume(ob.bid_total_volume)}</span></span>
        <span>卖盘总量: <span className="text-green-600 font-medium">{formatVolume(ob.ask_total_volume)}</span></span>
        <span>失衡: <span className={ob.imbalance > 0 ? "text-red-600" : "text-green-600"}>
          {ob.imbalance > 0 ? "+" : ""}{ob.imbalance.toFixed(3)}
        </span></span>
      </div>
    </div>
  );
}

/** 维度分析条 */
function DimensionBar({ dim }: { dim: DimensionSignal }) {
  const style = SIGNAL_STYLES[dim.signal] || SIGNAL_STYLES.neutral;
  // score: -100 ~ +100, 映射到 0 ~ 100 的条形宽度
  const pct = Math.abs(dim.score);
  const isPositive = dim.score >= 0;
  const barColor = isPositive ? "bg-red-400" : "bg-green-400";

  return (
    <div className="flex items-center gap-2 py-1">
      <span className="w-16 text-xs text-gray-600 shrink-0">{dim.name}</span>
      <div className="flex-1 h-3 bg-gray-100 rounded-full overflow-hidden relative">
        {/* 中线 */}
        <div className="absolute left-1/2 top-0 w-px h-full bg-gray-300 z-10" />
        {isPositive ? (
          <div
            className={`absolute left-1/2 top-0 h-full ${barColor} rounded-r-full transition-all duration-300`}
            style={{ width: `${pct / 2}%` }}
          />
        ) : (
          <div
            className={`absolute top-0 h-full ${barColor} rounded-l-full transition-all duration-300`}
            style={{ width: `${pct / 2}%`, right: "50%" }}
          />
        )}
      </div>
      <span className={`w-10 text-xs font-mono text-right shrink-0 ${style.text}`}>
        {dim.score > 0 ? "+" : ""}{dim.score.toFixed(0)}
      </span>
      <span className="text-xs text-gray-500 shrink-0">{dim.description}</span>
    </div>
  );
}

// ==================== 主组件 ====================

export function OrderBookPanel({ stockCode }: { stockCode: string }) {
  const [data, setData] = useState<OrderBookAnalysisData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    if (!stockCode.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const res = await getOrderBookAnalysis(stockCode.trim());
      if (res.success) {
        setData(res.data);
        if (!res.data) setError("暂无盘口数据");
      }
    } catch {
      setError("获取盘口数据失败");
    } finally {
      setLoading(false);
    }
  }, [stockCode]);

  // stockCode 变化时自动加载
  useEffect(() => {
    if (stockCode.trim()) fetchData();
  }, [stockCode, fetchData]);

  // 30秒自动刷新
  useEffect(() => {
    if (!stockCode.trim()) return;
    const timer = setInterval(fetchData, 30000);
    return () => clearInterval(timer);
  }, [stockCode, fetchData]);

  return (
    <div className="bg-white rounded-lg shadow p-6">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-lg font-semibold text-gray-900 flex items-center gap-2">
          <svg className="w-5 h-5 text-orange-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
          </svg>
          盘口深度分析
        </h3>
        <button
          onClick={fetchData}
          disabled={loading}
          className="text-xs text-gray-400 hover:text-gray-600 disabled:opacity-50"
        >
          {loading ? "刷新中..." : "刷新"}
        </button>
      </div>

      {error && <p className="text-sm text-red-500 mb-3">{error}</p>}

      {data && (
        <>
          <SummaryBadge data={data} />
          <OrderBookTable data={data} />

          {/* 5维度分析 */}
          <div className="mt-4">
            <div className="text-xs text-gray-500 mb-2 font-medium">5维度分析</div>
            <div className="space-y-0.5">
              {data.dimensions.map((dim) => (
                <DimensionBar key={dim.name} dim={dim} />
              ))}
            </div>
          </div>
        </>
      )}

      {!data && !loading && !error && (
        <p className="text-sm text-gray-400 text-center py-8">
          在资金流向中输入股票代码后，盘口分析将自动加载
        </p>
      )}
    </div>
  );
}
