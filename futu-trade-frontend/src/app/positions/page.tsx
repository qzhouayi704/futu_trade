"use client";

import { useState, useEffect, useCallback } from "react";
import { tradeApi } from "@/lib/api/trade";
import { IntradayLevelsPanel } from "@/app/market-scan/components/IntradayLevelsPanel";
import type { BackendPosition } from "@/types";

export default function PositionsPage() {
  const [positions, setPositions] = useState<BackendPosition[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchPositions = useCallback(async () => {
    try {
      const res = await tradeApi.getPositionsStandalone();
      if (res.success && res.data?.positions) {
        // 按盈亏比例排序（亏损优先关注）
        const sorted = [...res.data.positions].sort(
          (a, b) => a.pl_ratio - b.pl_ratio
        );
        setPositions(sorted);
        setError(null);
      } else {
        setError(res.message || "获取持仓失败");
      }
    } catch {
      setError("无法连接交易服务");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchPositions();
    const timer = setInterval(fetchPositions, 60_000);
    return () => clearInterval(timer);
  }, [fetchPositions]);

  const formatPL = (val: number) => {
    const abs = Math.abs(val);
    const str = abs >= 10000 ? `${(abs / 10000).toFixed(1)}万` : abs.toFixed(0);
    return val >= 0 ? `+${str}` : `-${str}`;
  };

  return (
    <div className="min-h-screen bg-gray-50 p-3 md:p-6">
      {/* 页面标题 */}
      <div className="flex flex-wrap items-center justify-between gap-2 mb-4 md:mb-6">
        <div className="flex items-center gap-2 md:gap-3">
          <h1 className="text-lg md:text-xl font-bold text-gray-800">📊 持仓监控</h1>
          <span className="text-xs md:text-sm text-gray-400">
            {positions.length} 只持仓
          </span>
        </div>
        <button
          onClick={() => { setLoading(true); fetchPositions(); }}
          className="px-3 py-1.5 bg-white border border-gray-200 rounded-lg text-sm text-gray-600 hover:bg-gray-50 transition-colors"
        >
          🔄 刷新
        </button>
      </div>

      {/* 持仓汇总 */}
      {positions.length > 0 && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 md:gap-4 mb-4 md:mb-6">
          <div className="bg-white rounded-lg border border-gray-200 p-4">
            <div className="text-xs text-gray-400 mb-1">总市值</div>
            <div className="text-lg font-bold text-gray-800">
              {(positions.reduce((s, p) => s + p.market_val, 0) / 10000).toFixed(1)}万
            </div>
          </div>
          <div className="bg-white rounded-lg border border-gray-200 p-4">
            <div className="text-xs text-gray-400 mb-1">总盈亏</div>
            {(() => {
              const total = positions.reduce((s, p) => s + p.pl_val, 0);
              return (
                <div className={`text-lg font-bold ${total >= 0 ? 'text-red-600' : 'text-green-600'}`}>
                  {formatPL(total)}
                </div>
              );
            })()}
          </div>
          <div className="bg-white rounded-lg border border-gray-200 p-4">
            <div className="text-xs text-gray-400 mb-1">盈利股</div>
            <div className="text-lg font-bold text-red-600">
              {positions.filter(p => p.pl_val > 0).length}
            </div>
          </div>
          <div className="bg-white rounded-lg border border-gray-200 p-4">
            <div className="text-xs text-gray-400 mb-1">亏损股</div>
            <div className="text-lg font-bold text-green-600">
              {positions.filter(p => p.pl_val < 0).length}
            </div>
          </div>
        </div>
      )}

      {/* 状态 */}
      {loading && (
        <div className="flex items-center justify-center py-20">
          <div className="w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
          <span className="ml-3 text-gray-400">获取持仓中...</span>
        </div>
      )}
      {error && !loading && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4 text-center text-red-600 text-sm">
          {error}
        </div>
      )}
      {!loading && !error && positions.length === 0 && (
        <div className="bg-white border border-gray-200 rounded-lg p-12 text-center text-gray-400">
          当前无持仓
        </div>
      )}

      {/* 持仓股票资金走势网格 */}
      {!loading && positions.length > 0 && (
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
          {positions.map((pos) => (
            <div key={pos.stock_code} className="relative">
              {/* 持仓信息条 */}
              <div className="bg-white border border-gray-200 rounded-t-lg px-3 md:px-4 py-2 flex flex-col md:flex-row md:items-center justify-between gap-1 md:gap-0">
                <div className="flex items-center gap-2 md:gap-3 flex-wrap">
                  <span className="font-bold text-gray-800">{pos.stock_name}</span>
                  <span className="text-xs text-gray-400">{pos.stock_code}</span>
                  <span className="text-xs text-gray-500">
                    {pos.qty}股 · 成本 {pos.cost_price.toFixed(3)}
                  </span>
                </div>
                <div className="flex items-center gap-2 md:gap-3 text-sm">
                  <span className="text-gray-500">
                    现价 <span className="font-medium text-gray-800">{pos.nominal_price.toFixed(3)}</span>
                  </span>
                  <span className={`font-bold ${pos.pl_val >= 0 ? 'text-red-600' : 'text-green-600'}`}>
                    {formatPL(pos.pl_val)} ({pos.pl_ratio >= 0 ? '+' : ''}{(pos.pl_ratio * 100).toFixed(2)}%)
                  </span>
                </div>
              </div>
              {/* 复用 IntradayLevelsPanel */}
              <div className="[&>div]:mt-0 [&>div]:rounded-t-none [&>div]:border-t-0">
                <IntradayLevelsPanel
                  stockCode={pos.stock_code}
                  stockName={pos.stock_name}
                  onClose={() => {}}
                  showClose={false}
                />
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
