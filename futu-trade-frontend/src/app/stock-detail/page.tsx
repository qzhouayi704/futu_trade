// 个股深度分析 — 单页 Dashboard（去掉Tab，滚动式布局）

"use client";

import { useState, useEffect, useCallback } from "react";
import { useSearchParams } from "next/navigation";
import dynamic from "next/dynamic";
import { stockApi } from "@/lib/api/stock";
import { getCapitalFlowTimeline, type CapitalFlowTimelinePoint } from "@/lib/api/enhanced-heat";
import type { TopHotStock } from "@/types";

import StockHeader from "./components/StockHeader";
import StrategyScoringCards from "./components/StrategyScoringCards";
import KeyMetricsPanel from "./components/KeyMetricsPanel";

// 动态加载重量级组件
const CapitalFlowChart = dynamic(
  () => import("@/app/enhanced-heat/components/CapitalFlowChart").then(m => m.CapitalFlowChart),
  { ssr: false }
);
const BigOrderTracker = dynamic(
  () => import("@/app/enhanced-heat/components/BigOrderTracker").then(m => m.BigOrderTracker),
  { ssr: false }
);
const IntradayFlowChart = dynamic(
  () => import("@/app/market-scan/components/CapitalFlowChart").then(m => m.CapitalFlowChart),
  { ssr: false }
);
const OrderBookPanel = dynamic(
  () => import("@/app/enhanced-heat/components/OrderBookPanel").then(m => m.OrderBookPanel),
  { ssr: false }
);
const TickerAnalysisPanel = dynamic(
  () => import("@/app/enhanced-heat/components/TickerAnalysisPanel").then(m => m.TickerAnalysisPanel),
  { ssr: false }
);
const IntradayCompositeChart = dynamic(
  () => import("./components/IntradayCompositeChart").then(m => m.IntradayCompositeChart),
  { ssr: false }
);
const SignalResonancePanel = dynamic(
  () => import("./components/SignalResonancePanel").then(m => m.SignalResonancePanel),
  { ssr: false }
);
const KlineDeltaChart = dynamic(
  () => import("./components/KlineDeltaChart").then(m => m.KlineDeltaChart),
  { ssr: false }
);


export default function StockDetailPage() {
  const searchParams = useSearchParams();
  const [stockCode, setStockCode] = useState("");
  const [searchInput, setSearchInput] = useState("");
  const [stock, setStock] = useState<TopHotStock | null>(null);
  const [loading, setLoading] = useState(false);
  const [flowTimeline, setFlowTimeline] = useState<CapitalFlowTimelinePoint[]>([]);

  // URL参数初始化
  useEffect(() => {
    const code = searchParams.get("code");
    if (code && !stockCode) {
      setStockCode(code);
      setSearchInput(code);
    }
  }, [searchParams]); // eslint-disable-line react-hooks/exhaustive-deps

  // 获取股票评分数据
  const fetchStockData = useCallback(async (code: string) => {
    if (!code) { setStock(null); return; }
    setLoading(true);
    try {
      const res = await stockApi.getTopHotStocks({ search: code.replace("HK.", ""), limit: 1 });
      if (res.success && res.data?.stocks && res.data.stocks.length > 0) {
        setStock(res.data.stocks[0]);
      } else {
        // 股票不在热门池中，构建最小对象以保证头部（含自选按钮）正常渲染
        setStock({ code, name: code, stock_code: code } as unknown as TopHotStock);
      }
    } catch { setStock({ code, name: code, stock_code: code } as unknown as TopHotStock); }
    setLoading(false);
  }, []);

  // 获取资金流时间线
  const fetchFlowTimeline = useCallback(async (code: string) => {
    if (!code) { setFlowTimeline([]); return; }
    try {
      const res = await getCapitalFlowTimeline(code);
      if (res.success && res.data) setFlowTimeline(res.data.timeline || []);
    } catch { /* ignore */ }
  }, []);

  // 自动刷新
  useEffect(() => {
    if (!stockCode) return;
    fetchStockData(stockCode);
    fetchFlowTimeline(stockCode);
    const timer = setInterval(() => {
      fetchStockData(stockCode);
      fetchFlowTimeline(stockCode);
    }, 30_000);
    return () => clearInterval(timer);
  }, [stockCode, fetchStockData, fetchFlowTimeline]);

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    const code = searchInput.trim();
    if (code) {
      const fullCode = code.startsWith("HK.") ? code : `HK.${code}`;
      setStockCode(fullCode);
    }
  };

  return (
    <div className="min-h-screen">
      {/* 顶部搜索栏 */}
      <div className="sticky top-0 z-20 bg-card/80 glass border-b border-border">
        <div className="flex items-center gap-4 px-5 py-2.5">
          <h1 className="text-base font-semibold text-foreground tracking-tight whitespace-nowrap">
            📊 个股深度
          </h1>
          <form onSubmit={handleSearch} className="flex-1 max-w-md">
            <div className="relative">
              <input
                type="text"
                value={searchInput}
                onChange={(e) => setSearchInput(e.target.value)}
                placeholder="输入股票代码，如 06651 或 HK.00981"
                className="w-full h-9 pl-9 pr-3 text-sm bg-background border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-primary/50 focus:border-primary"
              />
              <svg className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
              </svg>
            </div>
          </form>
          <div className="flex items-center gap-2">
            {stock && (
              <span className="text-xs text-muted-foreground">
                自动刷新 · 30s
              </span>
            )}
            {/* 快速操作按钮 */}
            {stockCode && (
              <div className="flex items-center gap-1.5">
                <a
                  href={`/pre-check?code=${stockCode}`}
                  className="text-xs px-2.5 py-1.5 rounded-lg bg-blue-500/10 text-blue-600 dark:text-blue-400 hover:bg-blue-500/20 transition-colors font-medium flex items-center gap-1"
                >
                  ⚡ 快速检查
                </a>
                <a
                  href={`/trading?stock=${stockCode}`}
                  className="text-xs px-2.5 py-1.5 rounded-lg bg-primary/10 text-primary hover:bg-primary/20 transition-colors font-medium flex items-center gap-1"
                >
                  📈 下单
                </a>
              </div>
            )}
          </div>
        </div>
      </div>


      {/* Dashboard 内容 */}
      <div className="p-5 space-y-5 max-w-[1600px] mx-auto">
        {!stockCode && !loading && (
          <div className="flex flex-col items-center justify-center py-20 text-muted-foreground">
            <span className="text-5xl mb-4">🔍</span>
            <p className="text-lg">输入股票代码开始深度分析</p>
            <p className="text-sm mt-1">支持港股代码，如 06651、00981</p>
          </div>
        )}

        {/* ① 股票头部 */}
        <StockHeader stock={stock} loading={loading} />

        {/* ② 三策略评分卡 */}
        <StrategyScoringCards stock={stock} />

        {/* ③ 关键指标面板 */}
        <KeyMetricsPanel stock={stock} />

        {/* ③.5 信号共振 + 日内分时叠加图 */}
        {stockCode && (
          <div className="grid grid-cols-1 xl:grid-cols-3 gap-5">
            <div className="xl:col-span-2">
              <IntradayCompositeChart stockCode={stockCode} />
            </div>
            <SignalResonancePanel stockCode={stockCode} />
          </div>
        )}

        {/* ③.8 5分钟K线+Delta联动图 */}
        {stockCode && (
          <KlineDeltaChart stockCode={stockCode} />
        )}

        {/* ④ 资金流向 + 大单追踪 */}
        {stockCode && (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
            <CapitalFlowChart stockCode={stockCode} onStockCodeChange={(c: string) => { setStockCode(c); setSearchInput(c); }} />
            <BigOrderTracker stockCode={stockCode} />
          </div>
        )}

        {/* ⑤ 主力 vs 散户 日内资金走势 */}
        {stockCode && flowTimeline.length > 0 && (
          <div className="bg-card rounded-xl border border-border overflow-hidden">
            <div className="px-4 py-2.5 bg-gradient-to-r from-blue-500/5 to-indigo-500/5 border-b border-border flex items-center justify-between">
              <span className="text-sm font-semibold text-foreground">📈 主力 vs 散户 日内资金走势</span>
              <span className="text-[10px] text-muted-foreground">30秒自动刷新</span>
            </div>
            <IntradayFlowChart data={flowTimeline} height={320} />
          </div>
        )}

        {/* ⑥ 盘口深度 + 逐笔成交 */}
        {stockCode && (
          <div className="grid grid-cols-1 xl:grid-cols-2 gap-5 items-start">
            <OrderBookPanel stockCode={stockCode} />
            <TickerAnalysisPanel stockCode={stockCode} />
          </div>
        )}
      </div>
    </div>
  );
}
