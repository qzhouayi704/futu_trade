// 资金流向可视化组件

"use client";

import { useState, useCallback } from "react";
import type { CapitalFlowData } from "@/types/enhanced-heat";
import { getCapitalFlow } from "@/lib/api/enhanced-heat";

/** 格式化金额（万/亿） */
function formatAmount(value: number): string {
  const abs = Math.abs(value);
  if (abs >= 1e8) return `${(value / 1e8).toFixed(2)}亿`;
  if (abs >= 1e4) return `${(value / 1e4).toFixed(1)}万`;
  return value.toFixed(0);
}

/** 流向条 */
function FlowBar({ label, inflow, outflow }: { label: string; inflow: number; outflow: number }) {
  const total = inflow + outflow;
  const inflowPct = total > 0 ? (inflow / total) * 100 : 50;

  return (
    <div className="mb-3">
      <div className="flex justify-between text-xs text-gray-600 mb-1">
        <span>{label}</span>
        <span className={inflow > outflow ? "text-red-600" : "text-green-600"}>
          净{inflow > outflow ? "流入" : "流出"} {formatAmount(Math.abs(inflow - outflow))}
        </span>
      </div>
      <div className="flex h-4 rounded-full overflow-hidden bg-gray-100">
        <div
          className="bg-red-400 transition-all duration-300"
          style={{ width: `${inflowPct}%` }}
          title={`流入: ${formatAmount(inflow)}`}
        />
        <div
          className="bg-green-400 transition-all duration-300"
          style={{ width: `${100 - inflowPct}%` }}
          title={`流出: ${formatAmount(outflow)}`}
        />
      </div>
      <div className="flex justify-between text-xs text-gray-400 mt-0.5">
        <span>流入 {formatAmount(inflow)}</span>
        <span>流出 {formatAmount(outflow)}</span>
      </div>
    </div>
  );
}

/** 指标卡片 */
function MetricCard({ label, value, suffix, color }: {
  label: string;
  value: number;
  suffix?: string;
  color: string;
}) {
  return (
    <div className="bg-gray-50 rounded-lg p-3 text-center">
      <div className="text-xs text-gray-500 mb-1">{label}</div>
      <div className={`text-lg font-bold ${color}`}>
        {(value * 100).toFixed(1)}{suffix || "%"}
      </div>
    </div>
  );
}

export function CapitalFlowChart({ stockCode, onStockCodeChange }: {
  stockCode: string;
  onStockCodeChange: (code: string) => void;
}) {
  const [inputCode, setInputCode] = useState(stockCode);
  const [data, setData] = useState<CapitalFlowData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    if (!inputCode.trim()) return;
    onStockCodeChange(inputCode.trim());
    setLoading(true);
    setError(null);
    try {
      const res = await getCapitalFlow(inputCode.trim());
      if (res.success) {
        setData(res.data);
        if (!res.data) setError("暂无该股票资金流向数据");
      }
    } catch {
      setError("获取资金流向失败");
    } finally {
      setLoading(false);
    }
  }, [inputCode, onStockCodeChange]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") fetchData();
  };

  return (
    <div className="bg-white rounded-lg shadow p-6">
      <h3 className="text-lg font-semibold text-gray-900 mb-4 flex items-center gap-2">
        <svg className="w-5 h-5 text-blue-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 12l3-3 3 3 4-4" />
        </svg>
        资金流向
      </h3>

      {/* 搜索框 */}
      <div className="flex gap-2 mb-4">
        <input
          type="text"
          value={inputCode}
          onChange={(e) => setInputCode(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="输入股票代码，如 HK.00700"
          className="flex-1 px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
        <button
          onClick={fetchData}
          disabled={loading || !inputCode.trim()}
          className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {loading ? "查询中..." : "查询"}
        </button>
      </div>

      {error && <p className="text-sm text-red-500 mb-3">{error}</p>}

      {data && (
        <>
          {/* 指标概览 */}
          <div className="grid grid-cols-3 gap-3 mb-4">
            <MetricCard
              label="主力净流入占比"
              value={data.net_inflow_ratio}
              color={data.net_inflow_ratio > 0 ? "text-red-600" : "text-green-600"}
            />
            <MetricCard
              label="大单买入占比"
              value={data.big_order_buy_ratio}
              color={data.big_order_buy_ratio > 0.5 ? "text-red-600" : "text-green-600"}
            />
            <MetricCard
              label="资金评分"
              value={data.capital_score / 100}
              suffix="分"
              color={data.capital_score > 60 ? "text-red-600" : "text-gray-600"}
            />
          </div>

          {/* 分级流向 */}
          <FlowBar label="超大单" inflow={data.super_large_inflow} outflow={data.super_large_outflow} />
          <FlowBar label="大单" inflow={data.large_inflow} outflow={data.large_outflow} />
          <FlowBar label="中单" inflow={data.medium_inflow} outflow={data.medium_outflow} />
          <FlowBar label="小单" inflow={data.small_inflow} outflow={data.small_outflow} />

          {/* 主力净流入 */}
          <div className="mt-3 p-3 bg-gray-50 rounded-lg">
            <div className="flex justify-between items-center">
              <span className="text-sm text-gray-600">主力净流入</span>
              <span className={`text-lg font-bold ${data.main_net_inflow > 0 ? "text-red-600" : "text-green-600"}`}>
                {data.main_net_inflow > 0 ? "+" : ""}{formatAmount(data.main_net_inflow)}
              </span>
            </div>
          </div>
        </>
      )}

      {!data && !loading && !error && (
        <p className="text-sm text-gray-400 text-center py-8">输入股票代码查询资金流向</p>
      )}
    </div>
  );
}
