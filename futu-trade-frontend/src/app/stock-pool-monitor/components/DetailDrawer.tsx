// Detail_Panel 抽屉组件 - 展示股票资金流向和盘口10档详情

"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import CapitalFlowDetail from "./CapitalFlowDetail";
import OrderBookDepth from "./OrderBookDepth";
import TickerInsight from "./TickerInsight";
import { getCapitalFlow, getOrderBookAnalysis } from "@/lib/api/enhanced-heat";
import type { CapitalFlowData, OrderBookResponse } from "@/types/enhanced-heat";

interface StockInfo {
  code: string;
  name: string;
}

interface DetailDrawerProps {
  stock: StockInfo | null;
  onClose: () => void;
}

interface DetailCacheEntry {
  capitalFlow: CapitalFlowData | null;
  orderBook: OrderBookResponse | null;
}

export default function DetailDrawer({ stock, onClose }: DetailDrawerProps) {
  const [loading, setLoading] = useState(false);
  const [capitalFlow, setCapitalFlow] = useState<CapitalFlowData | null>(null);
  const [orderBook, setOrderBook] = useState<OrderBookResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  // 缓存已加载的数据
  const cacheRef = useRef<Record<string, DetailCacheEntry>>({});

  const loadDetailData = useCallback(async (code: string) => {
    // 优先展示缓存
    const cached = cacheRef.current[code];
    if (cached) {
      setCapitalFlow(cached.capitalFlow);
      setOrderBook(cached.orderBook);
    }

    setLoading(!cached);
    setError(null);

    try {
      const [cfRes, obRes] = await Promise.allSettled([
        getCapitalFlow(code),
        getOrderBookAnalysis(code),
      ]);

      const cf = cfRes.status === "fulfilled" && cfRes.value.success ? cfRes.value.data : null;
      // 后端返回 OrderBookAnalysisData，需要提取其中的 order_book 字段
      const obData = obRes.status === "fulfilled" && obRes.value.success ? obRes.value.data : null;
      const ob: OrderBookResponse | null = obData?.order_book
        ? { stock_code: obData.stock_code, ...obData.order_book }
        : null;

      setCapitalFlow(cf);
      setOrderBook(ob);

      // 更新缓存
      cacheRef.current[code] = { capitalFlow: cf, orderBook: ob };
    } catch {
      if (!cached) {
        setError("数据加载失败");
      }
    } finally {
      setLoading(false);
    }
  }, []);

  // stock 变化时加载数据
  useEffect(() => {
    if (stock) {
      loadDetailData(stock.code);
    } else {
      setCapitalFlow(null);
      setOrderBook(null);
      setError(null);
    }
  }, [stock, loadDetailData]);

  if (!stock) return null;

  return (
    <>
      {/* 遮罩层 */}
      <div className="fixed inset-0 bg-black/30 z-40" onClick={onClose} />
      {/* 抽屉面板 */}
      <div className="fixed top-0 right-0 h-full w-96 bg-gray-900 border-l border-gray-700 z-50 overflow-y-auto shadow-2xl">
        {/* 头部 */}
        <div className="sticky top-0 bg-gray-900 border-b border-gray-700 p-4 flex items-center justify-between">
          <div>
            <h3 className="text-lg font-semibold text-white">{stock.name}</h3>
            <span className="text-sm text-gray-400">{stock.code}</span>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-white p-1">
            <i className="fas fa-times text-lg"></i>
          </button>
        </div>
        {/* 内容 */}
        <div className="p-4 space-y-6">
          {error && !capitalFlow && !orderBook ? (
            <div className="text-center py-8">
              <p className="text-gray-400 text-sm mb-3">{error}</p>
              <button
                onClick={() => loadDetailData(stock.code)}
                className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm rounded transition-colors"
              >
                重试
              </button>
            </div>
          ) : (
            <>
              <CapitalFlowDetail capitalFlow={capitalFlow} loading={loading} />
              <div className="border-t border-gray-700 pt-4">
                <h4 className="text-sm font-medium text-gray-300 mb-3">逐笔成交分析</h4>
                <TickerInsight stockCode={stock.code} />
              </div>
              <div className="border-t border-gray-700 pt-4">
                <h4 className="text-sm font-medium text-gray-300 mb-3">盘口10档</h4>
                <OrderBookDepth orderBook={orderBook} loading={loading} />
              </div>
            </>
          )}
        </div>
      </div>
    </>
  );
}
