// 板块股票详情页面

"use client";

import { useState, useEffect } from "react";
import { useParams, useRouter } from "next/navigation";
import { Card, Button, Loading } from "@/components/common";
import { stockApi } from "@/lib/api";
import { useSocket } from "@/lib/socket";
import { useToast } from "@/components/common/Toast";
import { formatPrice, formatPercent } from "@/lib/utils";
import type { Plate, PlateStock } from "@/types";

export default function PlateStocksPage() {
  const params = useParams();
  const router = useRouter();
  const { socket } = useSocket();
  const { showToast } = useToast();

  const plateCode = params.plateCode as string;

  const [plate, setPlate] = useState<Plate | null>(null);
  const [stocks, setStocks] = useState<PlateStock[]>([]);
  const [loading, setLoading] = useState(true);

  // 加载板块详情
  useEffect(() => {
    const loadPlateDetails = async () => {
      setLoading(true);
      try {
        const [plateResponse, stocksResponse] = await Promise.all([
          stockApi.getPlateByCode(plateCode),
          stockApi.getStocksByPlate(plateCode),
        ]);

        if (plateResponse.success && plateResponse.data) {
          setPlate(plateResponse.data);
        }
        if (stocksResponse.success && stocksResponse.data) {
          setStocks(stocksResponse.data);
        }
      } catch (err: unknown) {
        const message = err instanceof Error ? err.message : "加载板块详情失败";
        showToast("error", "错误", message);
      } finally {
        setLoading(false);
      }
    };

    if (plateCode) {
      loadPlateDetails();
    }
  }, [plateCode, showToast]);

  // 监听实时报价更新，合并到 stocks 中
  useEffect(() => {
    if (!socket) return;

    const handleQuotesUpdate = (data: { quotes?: Array<{ code: string; last_price?: number; change_percent?: number; volume?: number; turnover_rate?: number }> }) => {
      if (!data.quotes) return;
      const quotesMap = new Map(data.quotes.map((q) => [q.code, q]));

      setStocks((prev) =>
        prev.map((stock) => {
          const quote = quotesMap.get(stock.code);
          if (!quote) return stock;
          return {
            ...stock,
            last_price: quote.last_price ?? stock.last_price,
            change_percent: quote.change_percent ?? stock.change_percent,
            volume: quote.volume ?? stock.volume,
            turnover_rate: quote.turnover_rate ?? stock.turnover_rate,
            is_realtime: true,
          };
        })
      );
    };

    socket.on("quotes_update", handleQuotesUpdate);
    return () => {
      socket.off("quotes_update", handleQuotesUpdate);
    };
  }, [socket]);

  if (loading) {
    return <Loading fullScreen />;
  }

  return (
    <div className="container mx-auto px-4 py-6 max-w-7xl">
      {/* 页面标题 */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => router.back()}
            className="mb-2 flex items-center gap-1"
          >
            <i className="fas fa-arrow-left"></i>
            返回
          </Button>
          <h1 className="text-2xl font-bold text-gray-900">
            {plate?.plate_name || plateCode}
          </h1>
          <p className="text-gray-600 mt-1">
            板块代码: {plateCode} | 股票数量: {stocks.length}
          </p>
        </div>
      </div>

      {/* 股票列表 */}
      <Card>
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">代码</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">名称</th>
                <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase">最新价</th>
                <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase">涨跌幅</th>
                <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase">成交量</th>
                <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase">换手率</th>
              </tr>
            </thead>
            <tbody className="bg-white divide-y divide-gray-200">
              {stocks.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-6 py-8 text-center text-gray-500">暂无股票数据</td>
                </tr>
              ) : (
                stocks.map((stock) => {
                  const changePct = stock.change_percent ?? 0;
                  const isPositive = changePct > 0;
                  const isNegative = changePct < 0;
                  const colorClass = isPositive ? "text-red-600" : isNegative ? "text-green-600" : "text-gray-900";

                  return (
                    <tr key={stock.id} className="hover:bg-gray-50">
                      <td className="px-6 py-4 text-sm font-medium text-gray-900">{stock.code}</td>
                      <td className="px-6 py-4 text-sm text-gray-900">
                        {stock.name}
                      </td>
                      <td className={`px-6 py-4 text-sm text-right font-medium ${colorClass}`}>
                        {stock.last_price ? formatPrice(stock.last_price) : "-"}
                      </td>
                      <td className={`px-6 py-4 text-sm text-right font-medium ${colorClass}`}>
                        {stock.change_percent != null
                          ? `${isPositive ? "+" : ""}${formatPercent(changePct)}`
                          : "-"}
                      </td>
                      <td className="px-6 py-4 text-sm text-right text-gray-900">
                        {stock.volume || "-"}
                      </td>
                      <td className="px-6 py-4 text-sm text-right text-gray-900">
                        {stock.turnover_rate ? formatPercent(stock.turnover_rate) : "-"}
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
