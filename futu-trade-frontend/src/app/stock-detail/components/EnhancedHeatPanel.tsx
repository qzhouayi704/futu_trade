// 个股交易分析页面

"use client";

import { useState, useEffect, useCallback } from "react";
import { CapitalFlowChart } from "@/app/enhanced-heat/components/CapitalFlowChart";
import { CapitalFlowHistory } from "@/app/enhanced-heat/components/CapitalFlowHistory";
import { BigOrderTracker } from "@/app/enhanced-heat/components/BigOrderTracker";
import { OrderBookPanel } from "@/app/enhanced-heat/components/OrderBookPanel";
import { TickerAnalysisPanel } from "@/app/enhanced-heat/components/TickerAnalysisPanel";
import { getCapitalFlowTimeline, type CapitalFlowTimelinePoint } from "@/lib/api/enhanced-heat";
import dynamic from "next/dynamic";

const IntradayFlowChart = dynamic(
  () => import("@/app/market-scan/components/CapitalFlowChart").then(mod => mod.CapitalFlowChart),
  { ssr: false, loading: () => <div className="h-[340px] flex items-center justify-center bg-gray-50 rounded-lg"><div className="w-6 h-6 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" /></div> }
);

export default function EnhancedHeatPanel({ initialCode }: { initialCode?: string | null }) {
  const [stockCode, setStockCode] = useState("");
  const [flowTimeline, setFlowTimeline] = useState<CapitalFlowTimelinePoint[]>([]);

  // 从URL参数自动填入股票代码
  useEffect(() => {
    if (initialCode && !stockCode) {
      setStockCode(initialCode);
    }
  }, [initialCode]); // eslint-disable-line react-hooks/exhaustive-deps

  const fetchFlowTimeline = useCallback(async (code: string) => {
    if (!code) { setFlowTimeline([]); return; }
    try {
      const res = await getCapitalFlowTimeline(code);
      if (res.success && res.data) setFlowTimeline(res.data.timeline || []);
    } catch { /* ignore */ }
  }, []);

  useEffect(() => {
    fetchFlowTimeline(stockCode);
    if (!stockCode) return;
    const timer = setInterval(() => fetchFlowTimeline(stockCode), 30_000);
    return () => clearInterval(timer);
  }, [stockCode, fetchFlowTimeline]);

  return (
    <div className="p-6 space-y-6">
      <h1 className="text-2xl font-bold text-gray-900">个股交易分析</h1>

      {/* 资金流向 + 大单追踪 */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <CapitalFlowChart stockCode={stockCode} onStockCodeChange={setStockCode} />
        <BigOrderTracker stockCode={stockCode} />
      </div>

      {/* 主力 vs 散户 日内资金走势图 */}
      {stockCode && flowTimeline.length > 0 && (
        <div className="bg-white rounded-lg border border-gray-200 shadow-sm overflow-hidden">
          <div className="px-4 py-2 bg-gradient-to-r from-blue-50 to-indigo-50 border-b border-gray-100 flex items-center justify-between">
            <span className="text-sm font-semibold text-gray-700">📈 主力 vs 散户 日内资金走势</span>
            <span className="text-[10px] text-gray-400">30秒自动刷新</span>
          </div>
          <IntradayFlowChart data={flowTimeline} height={340} />
        </div>
      )}

      {/* 盘口深度 + 真实成交：双列并排 */}
      {stockCode && (
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-6 items-start">
          <OrderBookPanel stockCode={stockCode} />
          <TickerAnalysisPanel stockCode={stockCode} />
        </div>
      )}

      {/* 历史资金流向趋势 */}
      {stockCode && <CapitalFlowHistory stockCode={stockCode} />}
    </div>
  );
}

