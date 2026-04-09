// 历史资金流向趋势组件

"use client";

import { useState, useCallback, useEffect } from "react";
import type { CapitalFlowHistoryItem } from "@/types/enhanced-heat";
import { getCapitalFlowHistory } from "@/lib/api/enhanced-heat";

/** 格式化金额（万/亿） */
function formatAmount(value: number): string {
  const abs = Math.abs(value);
  if (abs >= 1e8) return `${(value / 1e8).toFixed(2)}亿`;
  if (abs >= 1e4) return `${(value / 1e4).toFixed(1)}万`;
  return value.toFixed(0);
}

/** 快捷日期范围 */
const DATE_RANGES = [
  { label: "7天", days: 7 },
  { label: "30天", days: 30 },
  { label: "90天", days: 90 },
] as const;

function toDateStr(d: Date): string {
  return d.toISOString().slice(0, 10);
}

/** 柱状图行 */
function BarRow({ item, maxAbs }: { item: CapitalFlowHistoryItem; maxAbs: number }) {
  const pct = maxAbs > 0 ? Math.abs(item.net_inflow) / maxAbs * 100 : 0;
  const isPositive = item.net_inflow >= 0;
  const dateLabel = item.date.slice(5, 10); // MM-DD

  return (
    <div className="flex items-center gap-2 py-1">
      <span className="text-xs text-gray-500 w-12 shrink-0">{dateLabel}</span>
      <div className="flex-1 flex items-center">
        {/* 左半（流出） */}
        <div className="w-1/2 flex justify-end">
          {!isPositive && (
            <div
              className="bg-green-400 rounded-l h-4 transition-all duration-300"
              style={{ width: `${pct}%` }}
            />
          )}
        </div>
        {/* 中线 */}
        <div className="w-px bg-gray-300 h-5 shrink-0" />
        {/* 右半（流入） */}
        <div className="w-1/2">
          {isPositive && (
            <div
              className="bg-red-400 rounded-r h-4 transition-all duration-300"
              style={{ width: `${pct}%` }}
            />
          )}
        </div>
      </div>
      <span className={`text-xs w-16 text-right shrink-0 ${isPositive ? "text-red-600" : "text-green-600"}`}>
        {formatAmount(item.net_inflow)}
      </span>
    </div>
  );
}

export function CapitalFlowHistory({ stockCode }: { stockCode: string }) {
  const [history, setHistory] = useState<CapitalFlowHistoryItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeDays, setActiveDays] = useState(30);

  const fetchHistory = useCallback(async (days: number) => {
    if (!stockCode.trim()) return;
    setLoading(true);
    setError(null);
    setActiveDays(days);

    const end = new Date();
    const start = new Date();
    start.setDate(end.getDate() - days);

    try {
      const res = await getCapitalFlowHistory(stockCode.trim(), toDateStr(start), toDateStr(end));
      if (res.success) {
        setHistory(res.data.history);
        if (res.data.history.length === 0) setError("暂无历史资金流向数据");
      }
    } catch {
      setError("获取历史资金流向失败");
    } finally {
      setLoading(false);
    }
  }, [stockCode]);

  // stockCode 变化时自动加载默认 30 天数据
  useEffect(() => {
    if (stockCode.trim()) {
      fetchHistory(30);
    }
  }, [stockCode, fetchHistory]);

  const maxAbs = history.reduce((m, item) => Math.max(m, Math.abs(item.net_inflow)), 0);

  // 累计净流入
  const totalNetInflow = history.reduce((sum, item) => sum + item.net_inflow, 0);
  const positiveCount = history.filter(d => d.net_inflow > 0).length;

  return (
    <div className="bg-white rounded-lg shadow p-6">
      <h3 className="text-lg font-semibold text-gray-900 mb-4 flex items-center gap-2">
        <svg className="w-5 h-5 text-purple-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6m6 0h6m-6 0V9a2 2 0 012-2h2a2 2 0 012 2v10m6 0v-4a2 2 0 00-2-2h-2a2 2 0 00-2 2v4" />
        </svg>
        历史资金流向
      </h3>

      {/* 快捷日期选择 */}
      <div className="flex gap-2 mb-4">
        {DATE_RANGES.map(({ label, days }) => (
          <button
            key={days}
            onClick={() => fetchHistory(days)}
            disabled={loading}
            className={`px-3 py-1.5 rounded-lg text-sm transition-colors ${
              activeDays === days && history.length > 0
                ? "bg-purple-600 text-white"
                : "bg-gray-100 text-gray-600 hover:bg-gray-200"
            } disabled:opacity-50`}
          >
            {label}
          </button>
        ))}
      </div>

      {loading && <p className="text-sm text-gray-400 text-center py-4">加载中...</p>}
      {error && <p className="text-sm text-red-500 mb-3">{error}</p>}

      {history.length > 0 && !loading && (
        <>
          {/* 汇总 */}
          <div className="grid grid-cols-3 gap-3 mb-4">
            <div className="bg-gray-50 rounded-lg p-3 text-center">
              <div className="text-xs text-gray-500 mb-1">累计净流入</div>
              <div className={`text-lg font-bold ${totalNetInflow >= 0 ? "text-red-600" : "text-green-600"}`}>
                {formatAmount(totalNetInflow)}
              </div>
            </div>
            <div className="bg-gray-50 rounded-lg p-3 text-center">
              <div className="text-xs text-gray-500 mb-1">净流入天数</div>
              <div className="text-lg font-bold text-gray-800">
                {positiveCount}/{history.length}
              </div>
            </div>
            <div className="bg-gray-50 rounded-lg p-3 text-center">
              <div className="text-xs text-gray-500 mb-1">流入占比</div>
              <div className={`text-lg font-bold ${positiveCount > history.length / 2 ? "text-red-600" : "text-green-600"}`}>
                {history.length > 0 ? ((positiveCount / history.length) * 100).toFixed(0) : 0}%
              </div>
            </div>
          </div>

          {/* 柱状图 */}
          <div className="max-h-80 overflow-y-auto">
            {history.map((item, i) => (
              <BarRow key={i} item={item} maxAbs={maxAbs} />
            ))}
          </div>
        </>
      )}

      {!loading && history.length === 0 && !error && (
        <p className="text-sm text-gray-400 text-center py-8">
          {stockCode ? "选择日期范围查看历史资金流向" : "请先在上方输入股票代码"}
        </p>
      )}
    </div>
  );
}
