// 大单追踪实时显示组件

"use client";

import { useState, useCallback, useEffect } from "react";
import type { BigOrderData } from "@/types/enhanced-heat";
import { getBigOrders } from "@/lib/api/enhanced-heat";

/** 格式化金额 */
function formatAmount(value: number): string {
  const abs = Math.abs(value);
  if (abs >= 1e8) return `${(value / 1e8).toFixed(2)}亿`;
  if (abs >= 1e4) return `${(value / 1e4).toFixed(1)}万`;
  return value.toFixed(0);
}

/** 强度仪表 */
function StrengthGauge({ strength }: { strength: number }) {
  // strength: -1 ~ 1
  const pct = ((strength + 1) / 2) * 100; // 转为 0-100
  const color = strength > 0.3 ? "bg-red-500" : strength < -0.3 ? "bg-green-500" : "bg-yellow-500";
  const label = strength > 0.3 ? "买入强势" : strength < -0.3 ? "卖出强势" : "均衡";

  return (
    <div className="bg-gray-50 rounded-lg p-3">
      <div className="flex justify-between text-xs text-gray-500 mb-1">
        <span>卖出</span>
        <span className="font-medium text-gray-700">{label}</span>
        <span>买入</span>
      </div>
      <div className="relative w-full h-3 bg-gray-200 rounded-full">
        {/* 中线 */}
        <div className="absolute left-1/2 top-0 w-0.5 h-3 bg-gray-400 z-10" />
        {/* 指示器 */}
        <div
          className={`absolute top-0 h-3 w-3 rounded-full ${color} border-2 border-white shadow transition-all duration-300`}
          style={{ left: `calc(${pct}% - 6px)` }}
        />
      </div>
      <div className="text-center mt-1">
        <span className={`text-lg font-bold ${strength > 0 ? "text-red-600" : "text-green-600"}`}>
          {strength > 0 ? "+" : ""}{strength.toFixed(2)}
        </span>
      </div>
    </div>
  );
}

/** 买卖比指示器 */
function BuySellRatio({ data }: { data: BigOrderData }) {
  const total = data.big_buy_amount + data.big_sell_amount;
  const buyPct = total > 0 ? (data.big_buy_amount / total) * 100 : 50;

  return (
    <div className="mb-4">
      <div className="flex justify-between text-xs text-gray-600 mb-1">
        <span>大单买入 {formatAmount(data.big_buy_amount)}</span>
        <span>大单卖出 {formatAmount(data.big_sell_amount)}</span>
      </div>
      <div className="flex h-5 rounded-full overflow-hidden">
        <div
          className="bg-red-400 flex items-center justify-center text-xs text-white font-medium transition-all duration-300"
          style={{ width: `${buyPct}%` }}
        >
          {buyPct > 15 && `${buyPct.toFixed(0)}%`}
        </div>
        <div
          className="bg-green-400 flex items-center justify-center text-xs text-white font-medium transition-all duration-300"
          style={{ width: `${100 - buyPct}%` }}
        >
          {(100 - buyPct) > 15 && `${(100 - buyPct).toFixed(0)}%`}
        </div>
      </div>
    </div>
  );
}

interface BigOrderTrackerProps {
  stockCode?: string;
}

export function BigOrderTracker({ stockCode: externalCode }: BigOrderTrackerProps) {
  const [localCode, setLocalCode] = useState("");
  const [data, setData] = useState<BigOrderData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 实际使用的股票代码：外部传入优先
  const activeCode = externalCode?.trim() || localCode.trim();

  const fetchData = useCallback(async (code?: string) => {
    const target = code ?? activeCode;
    if (!target) return;
    setLoading(true);
    setError(null);
    try {
      const res = await getBigOrders(target);
      if (res.success) {
        setData(res.data);
        if (!res.data) setError("暂无该股票大单数据");
      }
    } catch {
      setError("获取大单数据失败");
    } finally {
      setLoading(false);
    }
  }, [activeCode]);

  // 外部 stockCode 变化时自动查询
  useEffect(() => {
    if (externalCode?.trim()) {
      setLocalCode(externalCode.trim());
      fetchData(externalCode.trim());
    }
  }, [externalCode]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") fetchData();
  };

  return (
    <div className="bg-white rounded-lg shadow p-6">
      <h3 className="text-lg font-semibold text-gray-900 mb-4 flex items-center gap-2">
        <svg className="w-5 h-5 text-purple-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 14l6-6m-5.5.5h.01m4.99 5h.01M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16l3.5-2 3.5 2 3.5-2 3.5 2z" />
        </svg>
        大单追踪
      </h3>

      {/* 搜索框 */}
      <div className="flex gap-2 mb-4">
        <input
          type="text"
          value={localCode}
          onChange={(e) => setLocalCode(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="输入股票代码，如 HK.00700"
          className="flex-1 px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-purple-500"
        />
        <button
          onClick={() => fetchData()}
          disabled={loading || !activeCode}
          className="px-4 py-2 bg-purple-600 text-white rounded-lg text-sm hover:bg-purple-700 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {loading ? "查询中..." : "查询"}
        </button>
      </div>

      {error && <p className="text-sm text-red-500 mb-3">{error}</p>}

      {data && (
        <>
          {/* 大单统计 */}
          <div className="grid grid-cols-2 gap-3 mb-4">
            <div className="bg-red-50 rounded-lg p-3 text-center">
              <div className="text-xs text-red-600 mb-1">大单买入</div>
              <div className="text-xl font-bold text-red-700">{data.big_buy_count}</div>
              <div className="text-xs text-red-500">{formatAmount(data.big_buy_amount)}</div>
            </div>
            <div className="bg-green-50 rounded-lg p-3 text-center">
              <div className="text-xs text-green-600 mb-1">大单卖出</div>
              <div className="text-xl font-bold text-green-700">{data.big_sell_count}</div>
              <div className="text-xs text-green-500">{formatAmount(data.big_sell_amount)}</div>
            </div>
          </div>

          {/* 买卖比 */}
          <BuySellRatio data={data} />

          {/* 买卖比数值 */}
          <div className="bg-gray-50 rounded-lg p-3 mb-4 flex justify-between items-center">
            <span className="text-sm text-gray-600">买卖比</span>
            <span className={`text-lg font-bold ${data.buy_sell_ratio > 1 ? "text-red-600" : "text-green-600"}`}>
              {data.buy_sell_ratio.toFixed(2)}
            </span>
          </div>

          {/* 大单强度 */}
          <StrengthGauge strength={data.order_strength} />
        </>
      )}

      {!data && !loading && !error && (
        <p className="text-sm text-gray-400 text-center py-8">输入股票代码查询大单数据</p>
      )}
    </div>
  );
}
