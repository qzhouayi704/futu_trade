// 换仓/加仓对比详情面板

"use client";

import type { DecisionAdvice, PositionHealth } from "@/types/advisor";
import { AIAnalysisPanel } from "./AIAnalysisPanel";

interface SwapDetailProps {
  advice: DecisionAdvice | null;
}

export function SwapDetail({ advice }: SwapDetailProps) {
  if (!advice) {
    return (
      <div className="flex items-center justify-center h-32 text-gray-400 text-sm">
        点击左侧建议查看详情
      </div>
    );
  }

  const health = advice.position_health;
  const isSwap = advice.advice_type === "SWAP";
  const isAdd = advice.advice_type === "ADD_POSITION";

  return (
    <div className="space-y-3">
      {/* 标题 */}
      <div className="flex items-center gap-2">
        <h3 className="font-medium text-sm">{advice.title}</h3>
        <span className="text-xs px-2 py-0.5 rounded-full bg-blue-100 text-blue-700">
          {advice.advice_type_label}
        </span>
      </div>

      {/* 描述 */}
      <p className="text-sm text-gray-600">{advice.description}</p>

      {/* 对比面板 */}
      {(isSwap || isAdd) && (
        <div className="grid grid-cols-2 gap-4">
          {/* 卖出侧 */}
          {advice.sell_stock_code && (
            <StockPanel
              label="卖出"
              labelColor="text-green-600 bg-green-50"
              stockCode={advice.sell_stock_code}
              stockName={advice.sell_stock_name || ""}
              price={advice.sell_price}
              health={health}
            />
          )}

          {/* 买入侧 */}
          {advice.buy_stock_code && (
            <StockPanel
              label="买入"
              labelColor="text-red-600 bg-red-50"
              stockCode={advice.buy_stock_code}
              stockName={advice.buy_stock_name || ""}
              price={advice.buy_price}
              health={null}
            />
          )}
        </div>
      )}

      {/* 非换仓/加仓的详情 */}
      {!isSwap && !isAdd && health && (
        <div className="p-3 rounded-lg bg-gray-50 border border-gray-200">
          <div className="grid grid-cols-3 gap-3 text-sm">
            <MetricItem label="健康度" value={`${Math.round(health.score)}分`} />
            <MetricItem label="盈亏" value={`${health.profit_pct.toFixed(1)}%`}
              color={health.profit_pct >= 0 ? "text-red-500" : "text-green-500"} />
            <MetricItem label="趋势" value={
              health.trend === "UP" ? "向上" : health.trend === "DOWN" ? "向下" : "震荡"
            } />
            <MetricItem label="换手率" value={`${health.turnover_rate.toFixed(1)}%`} />
            <MetricItem label="量比" value={health.volume_ratio.toFixed(1)} />
            <MetricItem label="振幅" value={`${health.amplitude.toFixed(1)}%`} />
          </div>
        </div>
      )}

      {/* 卖出比例提示 */}
      {advice.sell_ratio && advice.sell_ratio < 1 && (
        <p className="text-xs text-gray-500">
          建议卖出比例: {Math.round(advice.sell_ratio * 100)}%
        </p>
      )}

      {/* AI 深度分析 */}
      {advice.ai_analysis && (
        <AIAnalysisPanel analysis={advice.ai_analysis} />
      )}
    </div>
  );
}

function StockPanel({
  label,
  labelColor,
  stockCode,
  stockName,
  price,
  health,
}: {
  label: string;
  labelColor: string;
  stockCode: string;
  stockName: string;
  price?: number;
  health: PositionHealth | null | undefined;
}) {
  return (
    <div className="p-3 rounded-lg bg-gray-50 border border-gray-200">
      <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${labelColor}`}>
        {label}
      </span>
      <div className="mt-2">
        <p className="font-medium text-sm">{stockName}</p>
        <p className="text-xs text-gray-500">{stockCode}</p>
        {price && price > 0 && (
          <p className="text-sm font-medium mt-1">${price.toFixed(2)}</p>
        )}
      </div>
      {health && (
        <div className="mt-2 pt-2 border-t border-gray-200 grid grid-cols-2 gap-1 text-xs text-gray-500">
          <span>健康度 {Math.round(health.score)}</span>
          <span>换手 {health.turnover_rate.toFixed(1)}%</span>
          <span>量比 {health.volume_ratio.toFixed(1)}</span>
          <span>振幅 {health.amplitude.toFixed(1)}%</span>
        </div>
      )}
    </div>
  );
}

function MetricItem({
  label,
  value,
  color,
}: {
  label: string;
  value: string;
  color?: string;
}) {
  return (
    <div>
      <p className="text-xs text-gray-400">{label}</p>
      <p className={`font-medium ${color || "text-gray-700"}`}>{value}</p>
    </div>
  );
}
