// 真实成交分析面板 - 4维度成交分析 + 9维度综合多空判断

"use client";

import { useState, useEffect, useCallback } from "react";
import type {
  DimensionSignal,
  SignalType,
  CombinedAnalysisData,
  VolumeCluster,
  PriceLevelDistributionData,
} from "@/types/enhanced-heat";
import { getTickerAnalysis, getCombinedAnalysis, getPriceDistribution } from "@/lib/api/enhanced-heat";
import { PriceLevelDistribution } from "./PriceLevelDistribution";
import { BuySellTimeline } from "./BuySellTimeline";
import { AllDimensionsChart } from "./AllDimensionsChart";

// ==================== 信号样式映射 ====================

const SIGNAL_STYLES: Record<SignalType, { bg: string; text: string; label: string }> = {
  bullish: { bg: "bg-red-100 border-red-200", text: "text-red-700", label: "看涨" },
  slightly_bullish: { bg: "bg-red-50 border-red-100", text: "text-red-600", label: "偏多" },
  neutral: { bg: "bg-gray-100 border-gray-200", text: "text-gray-600", label: "中性" },
  slightly_bearish: { bg: "bg-green-50 border-green-100", text: "text-green-600", label: "偏空" },
  bearish: { bg: "bg-green-100 border-green-200", text: "text-green-700", label: "看跌" },
};

function formatAmount(v: number): string {
  if (Math.abs(v) >= 100000000) return `${(v / 100000000).toFixed(2)}亿`;
  if (Math.abs(v) >= 10000) return `${(v / 10000).toFixed(1)}万`;
  return v.toLocaleString();
}

function formatVolume(v: number): string {
  if (v >= 10000) return `${(v / 10000).toFixed(1)}万`;
  return v.toLocaleString();
}

// ==================== 子组件 ====================

/** 综合判断标签（含矛盾警告） */
function CombinedSummaryBadge({ data }: { data: CombinedAnalysisData }) {
  const style = SIGNAL_STYLES[data.signal] || SIGNAL_STYLES.neutral;
  const bgClass = data.has_contradiction
    ? "bg-yellow-50 border-yellow-300"
    : style.bg;

  return (
    <div className={`rounded-lg border p-3 mb-4 ${bgClass}`}>
      <div className="flex items-center justify-between mb-1">
        <div className="flex items-center gap-2">
          <span className={`text-lg font-bold ${data.has_contradiction ? "text-yellow-700" : style.text}`}>
            {data.label}
          </span>
          {data.has_contradiction && (
            <span className="text-xs bg-yellow-200 text-yellow-800 px-1.5 py-0.5 rounded">
              ⚠ 信号矛盾
            </span>
          )}
        </div>
        <div className="flex items-center gap-3 text-sm">
          <span className="text-gray-500">
            挂单: <span className={data.order_book_score >= 0 ? "text-red-600" : "text-green-600"}>
              {data.order_book_score > 0 ? "+" : ""}{data.order_book_score.toFixed(1)}
            </span>
          </span>
          <span className="text-gray-500">
            成交: <span className={data.ticker_score >= 0 ? "text-red-600" : "text-green-600"}>
              {data.ticker_score > 0 ? "+" : ""}{data.ticker_score.toFixed(1)}
            </span>
          </span>
          <span className={`font-medium ${data.has_contradiction ? "text-yellow-700" : style.text}`}>
            综合: {data.combined_score > 0 ? "+" : ""}{data.combined_score.toFixed(1)}
          </span>
        </div>
      </div>
      <p className="text-sm text-gray-700">{data.summary}</p>
    </div>
  );
}


/** 主动买卖力量柱状对比图 */
function ActiveBuySellChart({ dimensions }: { dimensions: DimensionSignal[] }) {
  const dim = dimensions.find((d) => d.name === "主动买卖");
  if (!dim) return null;

  const details = dim.details as Record<string, number | string>;
  const buyTurnover = (details.buy_turnover as number) ?? 0;
  const sellTurnover = (details.sell_turnover as number) ?? 0;
  const netTurnover = (details.net_turnover as number) ?? 0;
  const buyRatio = (details.buy_sell_ratio as number) ?? 0;
  const maxTurnover = Math.max(buyTurnover, sellTurnover, 1);

  // 时间范围与趋势字段
  const timeStart = (details.time_range_start as string) ?? "";
  const timeEnd = (details.time_range_end as string) ?? "";
  const totalCount = (details.total_count as number) ?? 0;
  const trendDirection = (details.trend_direction as string) ?? "";
  const firstHalfRatio = (details.first_half_ratio as number) ?? 0;
  const secondHalfRatio = (details.second_half_ratio as number) ?? 0;

  return (
    <div className="mb-4">
      <div className="text-xs text-gray-500 mb-2 font-medium">主动买卖力量</div>

      {/* 数据时间范围 */}
      {timeStart ? (
        <div className="flex items-center justify-between text-xs text-gray-500 mb-2">
          <span>{timeStart} ~ {timeEnd}</span>
          <span>共 {totalCount} 笔</span>
        </div>
      ) : (
        <div className="text-xs text-gray-400 text-center mb-2">暂无成交数据</div>
      )}

      {/* 近期趋势标签 */}
      {trendDirection && (
        <div className="flex items-center justify-between text-xs mb-2">
          <span className={`px-1.5 py-0.5 rounded font-medium ${
            trendDirection === "买方增强" ? "bg-red-100 text-red-700" :
            trendDirection === "卖方增强" ? "bg-green-100 text-green-700" :
            "bg-gray-100 text-gray-600"
          }`}>
            {trendDirection}
          </span>
          <span className="text-gray-500">
            前半段 {(firstHalfRatio * 100).toFixed(1)}% → 后半段 {(secondHalfRatio * 100).toFixed(1)}%
          </span>
        </div>
      )}

      <div className="space-y-2">
        {/* 买入柱 */}
        <div className="flex items-center gap-2">
          <span className="w-12 text-xs text-red-600 shrink-0 text-right">买入</span>
          <div className="flex-1 h-5 bg-gray-100 rounded overflow-hidden">
            <div
              className="h-full bg-red-400 rounded transition-all duration-300"
              style={{ width: `${(buyTurnover / maxTurnover) * 100}%` }}
            />
          </div>
          <span className="w-16 text-xs text-gray-600 text-right shrink-0">
            {formatAmount(buyTurnover)}
          </span>
        </div>
        {/* 卖出柱 */}
        <div className="flex items-center gap-2">
          <span className="w-12 text-xs text-green-600 shrink-0 text-right">卖出</span>
          <div className="flex-1 h-5 bg-gray-100 rounded overflow-hidden">
            <div
              className="h-full bg-green-400 rounded transition-all duration-300"
              style={{ width: `${(sellTurnover / maxTurnover) * 100}%` }}
            />
          </div>
          <span className="w-16 text-xs text-gray-600 text-right shrink-0">
            {formatAmount(sellTurnover)}
          </span>
        </div>
      </div>
      {/* 汇总 */}
      <div className="flex justify-between text-xs text-gray-500 mt-2">
        <span>
          净额: <span className={netTurnover >= 0 ? "text-red-600" : "text-green-600"}>
            {netTurnover >= 0 ? "+" : ""}{formatAmount(netTurnover)}
          </span>
        </span>
        <span>
          力量比: <span className={buyRatio >= 1 ? "text-red-600" : "text-green-600"}>
            {buyRatio.toFixed(2)}
          </span>
        </span>
      </div>

      {/* 买卖比分时走势图 */}
      <BuySellTimeline dimensions={dimensions} />
    </div>
  );
}



/** 成交密集价位列表 */
function VolumeClusterList({ dimensions }: { dimensions: DimensionSignal[] }) {
  const dim = dimensions.find((d) => d.name === "密集价位");
  if (!dim) return null;

  // details.clusters 是后端返回的数组，需要类型断言
  const rawDetails = dim.details as unknown as { clusters?: VolumeCluster[]; cluster_count?: number };
  const clusters = rawDetails.clusters ?? [];
  if (clusters.length === 0) return null;

  return (
    <div>
      <div className="text-xs text-gray-500 mb-2 font-medium">成交密集价位</div>
      <div className="space-y-1">
        {clusters.map((c, i) => (
          <div key={i} className="flex items-center gap-2 py-1 px-2 bg-gray-50 rounded text-xs">
            <span className="font-mono text-gray-800 w-16 text-right">{c.price.toFixed(2)}</span>
            <span className={`px-1.5 py-0.5 rounded text-xs font-medium ${
              c.type === "support"
                ? "bg-red-100 text-red-700"
                : c.type === "resistance"
                  ? "bg-green-100 text-green-700"
                  : "bg-gray-100 text-gray-600"
            }`}>
              {c.type === "support" ? "支撑" : c.type === "resistance" ? "阻力" : "当前"}
            </span>
            <span className="text-gray-500">量: {formatVolume(c.volume)}</span>
            <div className="flex-1" />
            <span className="text-red-500">买{(c.buy_pct * 100).toFixed(0)}%</span>
            <span className="text-green-500">卖{(c.sell_pct * 100).toFixed(0)}%</span>
          </div>
        ))}
      </div>
    </div>
  );
}


/** 成交节奏文字描述 */
function TradeRhythmInfo({ dimensions }: { dimensions: DimensionSignal[] }) {
  const dim = dimensions.find((d) => d.name === "成交节奏");
  if (!dim) return null;

  const details = dim.details as Record<string, number | string>;
  const pattern = (details.pattern as string) ?? "未知";
  const changeRate = (details.change_rate as number) ?? 0;

  return (
    <div>
      <div className="text-xs text-gray-500 mb-1 font-medium">成交节奏</div>
      <div className="flex items-center gap-3 px-2 py-1.5 bg-gray-50 rounded">
        <span className="text-sm font-medium text-gray-800">{pattern}</span>
        <span className={`text-xs ${changeRate >= 0 ? "text-red-500" : "text-green-500"}`}>
          变化率: {changeRate >= 0 ? "+" : ""}{(changeRate * 100).toFixed(1)}%
        </span>
      </div>
    </div>
  );
}

// ==================== 主组件 ====================

export function TickerAnalysisPanel({ stockCode }: { stockCode: string }) {
  const [combinedData, setCombinedData] = useState<CombinedAnalysisData | null>(null);
  const [priceDistData, setPriceDistData] = useState<PriceLevelDistributionData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    if (!stockCode.trim()) return;
    setLoading(true);
    setError(null);
    try {
      // 并行请求成交分析、综合分析和价位分布
      const [tickerRes, combinedRes, priceDistRes] = await Promise.all([
        getTickerAnalysis(stockCode.trim()),
        getCombinedAnalysis(stockCode.trim()),
        getPriceDistribution(stockCode.trim()),
      ]);

      if (combinedRes.success && combinedRes.data) {
        setCombinedData(combinedRes.data);
      } else if (tickerRes.success && !tickerRes.data) {
        // 成交数据不可用但综合分析可能降级返回
        if (combinedRes.success && combinedRes.data) {
          setCombinedData(combinedRes.data);
        } else {
          setError("成交数据暂不可用");
        }
      } else {
        setError("获取分析数据失败");
      }

      // 价位分布数据独立更新，不影响其他分析内容
      if (priceDistRes.success && priceDistRes.data) {
        setPriceDistData(priceDistRes.data);
      }
    } catch {
      setError("获取成交分析数据失败");
    } finally {
      setLoading(false);
    }
  }, [stockCode]);

  // stockCode 变化时自动加载
  useEffect(() => {
    if (stockCode.trim()) fetchData();
  }, [stockCode, fetchData]);

  // 15秒自动刷新（成交数据变化快）
  useEffect(() => {
    if (!stockCode.trim()) return;
    const timer = setInterval(fetchData, 15000);
    return () => clearInterval(timer);
  }, [stockCode, fetchData]);

  const tickerUnavailable = combinedData && !combinedData.ticker_available;

  return (
    <div className="bg-white rounded-lg shadow p-6">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-lg font-semibold text-gray-900 flex items-center gap-2">
          <svg className="w-5 h-5 text-blue-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
              d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" />
          </svg>
          真实成交分析
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

      {tickerUnavailable && (
        <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-3 mb-4">
          <p className="text-sm text-yellow-700">
            ⚠ 成交数据暂不可用，当前仅展示挂单分析结果
          </p>
        </div>
      )}

      {combinedData && (
        <>
          <CombinedSummaryBadge data={combinedData} />

          {combinedData.ticker_available && (
            <div className="space-y-4">
              <ActiveBuySellChart dimensions={combinedData.ticker_dimensions} />

              <div className="bg-gray-50 rounded-lg p-3">
                <PriceLevelDistribution data={priceDistData} />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div className="bg-gray-50 rounded-lg p-3">
                  <VolumeClusterList dimensions={combinedData.ticker_dimensions} />
                </div>
                <div className="bg-gray-50 rounded-lg p-3">
                  <TradeRhythmInfo dimensions={combinedData.ticker_dimensions} />
                </div>
              </div>
            </div>
          )}

          <AllDimensionsChart data={combinedData} />
        </>
      )}

      {!combinedData && !loading && !error && (
        <p className="text-sm text-gray-400 text-center py-8">
          在资金流向中输入股票代码后，成交分析将自动加载
        </p>
      )}
    </div>
  );
}
