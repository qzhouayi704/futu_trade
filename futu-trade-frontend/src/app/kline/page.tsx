// K线图页面

"use client";

import { useState, useEffect } from "react";
import { Card, Button } from "@/components/common";
import { stockApi } from "@/lib/api";
import { useToast } from "@/components/common/Toast";
import { KlineChart } from "@/components/charts/KlineChart";
import type { Stock } from "@/types";

export default function KlinePage() {
  const { showToast } = useToast();

  const [stocks, setStocks] = useState<Stock[]>([]);
  const [selectedStock, setSelectedStock] = useState<string>("");
  const [period, setPeriod] = useState<"day" | "week" | "month">("day");
  const [loading, setLoading] = useState(false);

  // 加载股票列表
  const loadStocks = async () => {
    try {
      const response = await stockApi.getStocks({ limit: 100 });
      if (response.success && response.data) {
        setStocks(response.data);
        if (response.data.length > 0) {
          setSelectedStock(response.data[0].code);
        }
      }
    } catch (err: unknown) {
      console.error("加载股票列表失败:", err);
    }
  };

  // 初始化加载
  useEffect(() => {
    loadStocks();
  }, []);

  return (
    <div className="container mx-auto px-4 py-6 max-w-7xl">
      {/* 页面标题和控制区 */}
      <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4 mb-6">
        <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100 flex items-center gap-2">
          <i className="fas fa-chart-candlestick text-blue-600"></i>
          K线图
        </h1>

        <div className="flex flex-col md:flex-row gap-3">
          {/* 股票选择器 */}
          <select
            value={selectedStock}
            onChange={(e) => setSelectedStock(e.target.value)}
            className="px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100"
          >
            <option value="">选择股票</option>
            {stocks.map((stock) => (
              <option key={stock.id} value={stock.code}>
                {stock.code} - {stock.name}
              </option>
            ))}
          </select>

          {/* 周期选择器 */}
          <div className="flex gap-2">
            <button
              onClick={() => setPeriod("day")}
              className={`px-4 py-2 rounded-md font-medium transition-colors ${
                period === "day"
                  ? "bg-blue-600 text-white"
                  : "bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-600"
              }`}
            >
              日K
            </button>
            <button
              onClick={() => setPeriod("week")}
              className={`px-4 py-2 rounded-md font-medium transition-colors ${
                period === "week"
                  ? "bg-blue-600 text-white"
                  : "bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-600"
              }`}
            >
              周K
            </button>
            <button
              onClick={() => setPeriod("month")}
              className={`px-4 py-2 rounded-md font-medium transition-colors ${
                period === "month"
                  ? "bg-blue-600 text-white"
                  : "bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-600"
              }`}
            >
              月K
            </button>
          </div>
        </div>
      </div>

      {/* K线图表 */}
      <Card>
        {!selectedStock ? (
          <div className="flex items-center justify-center" style={{ height: "600px" }}>
            <div className="text-center">
              <i className="fas fa-chart-line text-4xl text-gray-400 mb-3"></i>
              <div className="text-gray-600 dark:text-gray-400">请选择股票查看K线图</div>
            </div>
          </div>
        ) : (
          <KlineChart
            stockCode={selectedStock}
            period={period}
            height={600}
            showVolume={true}
            showMA={true}
            showTradePoints={false}
            enableRealtime={false}
          />
        )}
      </Card>

      {/* 技术指标说明 */}
      <Card className="mt-6">
        <h2 className="text-lg font-medium text-gray-900 dark:text-gray-100 mb-4">技术指标说明</h2>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div className="p-4 bg-gray-50 dark:bg-gray-800 rounded-lg">
            <h3 className="font-medium text-gray-900 dark:text-gray-100 mb-2">MA（移动平均线）</h3>
            <p className="text-sm text-gray-600 dark:text-gray-400">
              显示5日、10日、20日、60日移动平均线，用于判断趋势方向
            </p>
          </div>
          <div className="p-4 bg-gray-50 dark:bg-gray-800 rounded-lg">
            <h3 className="font-medium text-gray-900 dark:text-gray-100 mb-2">成交量</h3>
            <p className="text-sm text-gray-600 dark:text-gray-400">
              显示每日成交量柱状图，涨红跌绿，用于判断市场活跃度
            </p>
          </div>
          <div className="p-4 bg-gray-50 dark:bg-gray-800 rounded-lg">
            <h3 className="font-medium text-gray-900 dark:text-gray-100 mb-2">交互功能</h3>
            <p className="text-sm text-gray-600 dark:text-gray-400">
              支持鼠标滚轮缩放、拖拽平移、十字光标查看详情
            </p>
          </div>
        </div>
      </Card>
    </div>
  );
}
