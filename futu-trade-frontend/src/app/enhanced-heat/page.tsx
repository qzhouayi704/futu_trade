// 个股交易分析页面

"use client";

import { useState } from "react";
import { CapitalFlowChart } from "./components/CapitalFlowChart";
import { CapitalFlowHistory } from "./components/CapitalFlowHistory";
import { BigOrderTracker } from "./components/BigOrderTracker";
import { OrderBookPanel } from "./components/OrderBookPanel";
import { TickerAnalysisPanel } from "./components/TickerAnalysisPanel";
import { ScalpingChart } from "./components/scalping/ScalpingChart";

export default function EnhancedHeatPage() {
  const [stockCode, setStockCode] = useState("");

  return (
    <div className="p-6 space-y-6">
      <h1 className="text-2xl font-bold text-gray-900">个股交易分析</h1>

      {/* 资金流向 + 大单追踪 */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <CapitalFlowChart stockCode={stockCode} onStockCodeChange={setStockCode} />
        <BigOrderTracker stockCode={stockCode} />
      </div>

      {/* 盘口深度 + 真实成交：双列并排 */}
      {stockCode && (
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-6 items-start">
          <OrderBookPanel stockCode={stockCode} />
          <TickerAnalysisPanel stockCode={stockCode} />
        </div>
      )}

      {/* 日内超短线作战图表 */}
      {stockCode && <ScalpingChart stockCode={stockCode} />}

      {/* 历史资金流向趋势 */}
      {stockCode && <CapitalFlowHistory stockCode={stockCode} />}
    </div>
  );
}
