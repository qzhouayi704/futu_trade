// 三级筛选结果展示组件

"use client";

import { useEffect, useState, useCallback } from "react";
import type { LeaderStocksData, LeaderStockItem } from "@/types/enhanced-heat";
import { getLeaderStocks } from "@/lib/api/enhanced-heat";

/** 漏斗步骤 */
function FunnelStep({ level, label, count, color }: {
  level: number;
  label: string;
  count: number;
  color: string;
}) {
  const widths = ["w-full", "w-4/5", "w-3/5", "w-2/5"];
  return (
    <div className="flex items-center gap-3 mb-2">
      <div className={`${widths[level]} ${color} rounded-lg py-2 px-4 text-white text-sm font-medium flex justify-between`}>
        <span>{label}</span>
        <span>{count}只</span>
      </div>
    </div>
  );
}

/** 信号强度条 */
function SignalBar({ strength }: { strength: number }) {
  const pct = Math.round(strength * 100);
  const color = pct >= 70 ? "bg-red-500" : pct >= 50 ? "bg-orange-500" : "bg-yellow-500";
  return (
    <div className="flex items-center gap-2">
      <div className="w-16 bg-gray-200 rounded-full h-2">
        <div className={`h-2 rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs text-gray-500">{pct}%</span>
    </div>
  );
}

/** 格式化价格位置，-1/NaN/undefined 显示 N/A */
function formatPricePosition(value: number | undefined | null): string {
  if (value === undefined || value === null || value === -1 || Number.isNaN(value)) {
    return "N/A";
  }
  return `${value.toFixed(1)}%`;
}

/** 格式化市值 */
function formatMarketCap(value: number | undefined | null): string {
  if (!value || value <= 0) return "-";
  if (value >= 1e8) return `${(value / 1e8).toFixed(1)}亿`;
  if (value >= 1e4) return `${(value / 1e4).toFixed(1)}万`;
  return value.toFixed(0);
}

/** 龙头股行 */
function LeaderRow({ stock }: { stock: LeaderStockItem }) {
  const rankColors = ["text-red-600", "text-orange-500", "text-yellow-600"];
  const rankColor = stock.leader_rank <= 3 ? rankColors[stock.leader_rank - 1] : "text-gray-500";
  const pricePositionText = formatPricePosition(stock.price_position);

  return (
    <tr className="border-b border-gray-100 hover:bg-gray-50">
      <td className="py-2 px-2">
        <span className={`font-bold ${rankColor}`}>
          {stock.is_leader ? `龙${stock.leader_rank}` : "-"}
        </span>
      </td>
      <td className="py-2 px-2">
        <div className="text-sm font-medium text-gray-900">{stock.stock_name}</div>
        <div className="text-xs text-gray-400">{stock.stock_code}</div>
      </td>
      <td className="py-2 px-2 text-xs text-gray-500">{stock.plate_name}</td>
      <td className="py-2 px-2 text-right text-sm">{stock.last_price.toFixed(3)}</td>
      <td className={`py-2 px-2 text-right text-sm font-medium ${stock.change_pct > 0 ? "text-red-600" : "text-green-600"}`}>
        {stock.change_pct > 0 ? "+" : ""}{stock.change_pct.toFixed(2)}%
      </td>
      <td className={`py-2 px-2 text-right text-sm ${pricePositionText === "N/A" ? "text-gray-400" : "text-gray-600"}`}>
        {pricePositionText}
      </td>
      <td className="py-2 px-2 text-right text-sm">
        <span className="inline-flex items-center rounded-full bg-blue-50 px-2 py-0.5 text-xs font-medium text-blue-700">
          {stock.leader_score?.toFixed(1) ?? "-"}
        </span>
      </td>
      <td className="py-2 px-2 text-center text-sm">
        {stock.consecutive_strong_days != null && stock.consecutive_strong_days > 0 ? (
          <span className="inline-flex items-center gap-0.5 text-red-600 font-medium">
            {stock.consecutive_strong_days}<span className="text-xs">天</span>
          </span>
        ) : (
          <span className="text-gray-400">-</span>
        )}
      </td>
      <td className="py-2 px-2">
        <SignalBar strength={stock.signal_strength} />
      </td>
    </tr>
  );
}


export function ScreeningResult() {
  const [data, setData] = useState<LeaderStocksData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const dataReady = data?.data_ready ?? false;

  const fetchData = useCallback(async () => {
    try {
      const res = await getLeaderStocks(20);
      if (res.success && res.data) {
        setData(res.data);
        setError(null);
      }
    } catch {
      setError("获取筛选结果失败");
    } finally {
      setLoading(false);
    }
  }, []);

  // 数据未就绪时 10s 轮询，就绪后 60s 轮询
  useEffect(() => {
    fetchData();
    const interval = dataReady ? 60000 : 10000;
    const timer = setInterval(fetchData, interval);
    return () => clearInterval(timer);
  }, [fetchData, dataReady]);

  if (loading) {
    return (
      <div className="bg-white rounded-lg shadow p-6 animate-pulse">
        <div className="h-6 bg-gray-200 rounded w-1/3 mb-4" />
        <div className="h-40 bg-gray-200 rounded" />
      </div>
    );
  }

  return (
    <div className="bg-white rounded-lg shadow p-6">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-lg font-semibold text-gray-900 flex items-center gap-2">
          <svg className="w-5 h-5 text-green-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 4a1 1 0 011-1h16a1 1 0 011 1v2.586a1 1 0 01-.293.707l-6.414 6.414a1 1 0 00-.293.707V17l-4 4v-6.586a1 1 0 00-.293-.707L3.293 7.293A1 1 0 013 6.586V4z" />
          </svg>
          三级筛选结果
        </h3>
        <button
          onClick={fetchData}
          className="text-sm text-blue-600 hover:text-blue-800"
        >
          刷新
        </button>
      </div>

      {/* 漏斗图 */}
      <div className="mb-6">
        <FunnelStep level={0} label="全部股票池" count={data?.screening_stats?.total_count ?? 0} color="bg-gray-400" />
        <FunnelStep level={1} label="基础筛选（有报价+成交量）" count={data?.screening_stats?.level1_count ?? 0} color="bg-blue-400" />
        <FunnelStep level={2} label="热度筛选（涨幅区间）" count={data?.screening_stats?.level2_count ?? 0} color="bg-orange-400" />
        <FunnelStep level={3} label="龙头确认（板块+排名）" count={data?.screening_stats?.level3_count ?? data?.total ?? 0} color="bg-red-500" />
      </div>

      {error && <p className="text-sm text-red-500 mb-3">{error}</p>}

      {/* 等待行情数据提示 */}
      {data && !dataReady && (
        <div className="flex items-center gap-2 text-sm text-amber-600 bg-amber-50 rounded-lg px-4 py-2 mb-3">
          <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
          </svg>
          等待行情数据，筛选结果将在报价就绪后自动更新...
        </div>
      )}

      {/* 龙头股列表 */}
      {data && data.leaders.length > 0 ? (
        <div className="overflow-x-auto">
          <table className="w-full text-left">
            <thead>
              <tr className="border-b-2 border-gray-200">
                <th className="py-2 px-2 text-xs font-medium text-gray-500">排名</th>
                <th className="py-2 px-2 text-xs font-medium text-gray-500">股票</th>
                <th className="py-2 px-2 text-xs font-medium text-gray-500">板块</th>
                <th className="py-2 px-2 text-xs font-medium text-gray-500 text-right">价格</th>
                <th className="py-2 px-2 text-xs font-medium text-gray-500 text-right">涨幅</th>
                <th className="py-2 px-2 text-xs font-medium text-gray-500 text-right">价格位置</th>
                <th className="py-2 px-2 text-xs font-medium text-gray-500 text-right">龙头评分</th>
                <th className="py-2 px-2 text-xs font-medium text-gray-500 text-center">连续强势</th>
                <th className="py-2 px-2 text-xs font-medium text-gray-500">信号强度</th>
              </tr>
            </thead>
            <tbody>
              {data.leaders.map((stock) => (
                <LeaderRow key={stock.stock_code} stock={stock} />
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="text-sm text-gray-400 text-center py-4">暂无龙头股数据</p>
      )}
    </div>
  );
}
